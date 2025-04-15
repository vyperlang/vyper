import pytest
import rlp
from eth.codecs import abi
from hexbytes import HexBytes

import vyper.ir.compile_ir as compile_ir
from tests.utils import ZERO_ADDRESS
from vyper.codegen.ir_node import IRnode
from vyper.compiler import compile_code
from vyper.compiler.settings import OptimizationLevel
from vyper.utils import EIP_170_LIMIT, ERC5202_PREFIX, checksum_encode, keccak256


# initcode used by create_minimal_proxy_to
def eip1167_initcode(_addr):
    addr = HexBytes(_addr)
    pre = HexBytes("0x602D3D8160093D39F3363d3d373d3d3d363d73")
    post = HexBytes("0x5af43d82803e903d91602b57fd5bf3")
    return HexBytes(pre + (addr + HexBytes(0) * (20 - len(addr))) + post)


# initcode used by CreateCopyOf
def vyper_initcode(runtime_bytecode):
    bytecode_len_hex = hex(len(runtime_bytecode))[2:].rjust(6, "0")
    return HexBytes("0x62" + bytecode_len_hex + "3d81600b3d39f3") + runtime_bytecode


def test_create_minimal_proxy_to_create(get_contract):
    code = """
main: address

@external
def test() -> address:
    self.main = create_minimal_proxy_to(self)
    return self.main
    """

    c = get_contract(code)

    address_bits = int(c.address, 16)
    nonce = 1
    rlp_encoded = rlp.encode([address_bits, nonce])
    expected_create_address = keccak256(rlp_encoded)[12:].rjust(20, b"\x00")
    assert c.test() == checksum_encode("0x" + expected_create_address.hex())


def test_create_minimal_proxy_to_call(get_contract):
    code = """
interface SubContract:
    def hello() -> Bytes[100]: view

other: public(address)

@external
def test() -> address:
    self.other = create_minimal_proxy_to(self)
    return self.other

@external
def hello() -> Bytes[100]:
    return b"hello world!"

@external
def test2() -> Bytes[100]:
    return staticcall SubContract(self.other).hello()
    """

    c = get_contract(code)

    assert c.hello() == b"hello world!"
    c.test()
    assert c.test2() == b"hello world!"


def test_minimal_proxy_exception(env, get_contract, tx_failed):
    code = """
interface SubContract:
    def hello(a: uint256) -> Bytes[100]: view

other: public(address)

@external
def test() -> address:
    self.other = create_minimal_proxy_to(self)
    return self.other

@external
def hello(a: uint256) -> Bytes[100]:
    assert a > 0, "invaliddddd"
    return b"hello world!"

@external
def test2(a: uint256) -> Bytes[100]:
    return staticcall SubContract(self.other).hello(a)
    """

    c = get_contract(code)

    assert c.hello(1) == b"hello world!"
    c.test()
    assert c.test2(1) == b"hello world!"

    with tx_failed(exc_text="invaliddddd"):
        c.test2(0)

    gas_sent = 30000
    with tx_failed(exc_text="invaliddddd"):
        c.test2(0, gas=gas_sent)

    # check we issued `revert`, which does not consume all gas
    assert env.last_result.gas_used < gas_sent


@pytest.mark.parametrize("revert_on_failure", [True, False, None])
def test_create_minimal_proxy_to_create2(
    get_contract, create2_address_of, keccak, tx_failed, revert_on_failure
):
    revert_arg = "" if revert_on_failure is None else f", revert_on_failure={revert_on_failure}"
    code = f"""
main: address

@external
def test(_salt: bytes32) -> address:
    self.main = create_minimal_proxy_to(self, salt=_salt{revert_arg})
    return self.main
    """

    c = get_contract(code)

    salt = keccak(b"vyper")
    result = c.test(salt)
    assert HexBytes(result) == create2_address_of(c.address, salt, eip1167_initcode(c.address))

    # revert on collision
    if revert_on_failure is False:
        assert c.test(salt) == ZERO_ADDRESS
    else:
        with tx_failed():
            c.test(salt)


# test blueprints with various prefixes - 0xfe would block calls to the blueprint
# contract, and 0xfe7100 is ERC5202 magic
@pytest.mark.parametrize("blueprint_prefix", [b"", b"\xfe", ERC5202_PREFIX])
@pytest.mark.parametrize("revert_on_failure", [True, False, None])
def test_create_from_blueprint(
    get_contract,
    deploy_blueprint_for,
    env,
    keccak,
    create2_address_of,
    tx_failed,
    blueprint_prefix,
    revert_on_failure,
):
    revert_arg = "" if revert_on_failure is None else f", revert_on_failure={revert_on_failure}"
    code = """
@external
def foo() -> uint256:
    return 123
    """

    prefix_len = len(blueprint_prefix)
    deployer_code = f"""
created_address: public(address)

@external
def test(target: address):
    self.created_address = create_from_blueprint(target, code_offset={prefix_len}{revert_arg})

@external
def test2(target: address, salt: bytes32):
    self.created_address = create_from_blueprint(
        target, code_offset={prefix_len}, salt=salt{revert_arg}
    )
    """

    # deploy a foo, so we can compare its bytecode with factory deployed version
    foo_contract = get_contract(code)
    expected_runtime_code = env.get_code(foo_contract.address)

    f, FooContract = deploy_blueprint_for(code, initcode_prefix=blueprint_prefix)

    d = get_contract(deployer_code)

    d.test(f.address)

    test = FooContract(d.created_address())
    assert env.get_code(test.address) == expected_runtime_code
    assert test.foo() == 123

    # extcodesize check
    zero_address = "0x" + "00" * 20
    with tx_failed():
        d.test(zero_address)

    # now same thing but with create2
    salt = keccak(b"vyper")
    d.test2(f.address, salt)

    test = FooContract(d.created_address())
    assert env.get_code(test.address) == expected_runtime_code
    assert test.foo() == 123

    # check if the create2 address matches our offchain calculation
    initcode = env.get_code(f.address)
    initcode = initcode[len(blueprint_prefix) :]  # strip the prefix
    assert HexBytes(test.address) == create2_address_of(d.address, salt, initcode)

    # can't collide addresses
    if revert_on_failure is False:
        assert not d.test2(f.address, salt)
    else:
        with tx_failed():
            d.test2(f.address, salt)


# test blueprints with 0xfe7100 prefix, which is the EIP 5202 standard.
# code offset by default should be 3 here.
def test_create_from_blueprint_default_offset(
    get_contract, deploy_blueprint_for, env, keccak, create2_address_of, tx_failed
):
    code = """
@external
def foo() -> uint256:
    return 123
    """

    deployer_code = """
created_address: public(address)

@external
def test(target: address):
    self.created_address = create_from_blueprint(target)

@external
def test2(target: address, salt: bytes32):
    self.created_address = create_from_blueprint(target, salt=salt)
    """

    # deploy a foo so we can compare its bytecode with factory deployed version
    foo_contract = get_contract(code)
    expected_runtime_code = env.get_code(foo_contract.address)

    f, FooContract = deploy_blueprint_for(code)

    d = get_contract(deployer_code)

    d.test(f.address)

    test = FooContract(d.created_address())
    assert env.get_code(test.address) == expected_runtime_code
    assert test.foo() == 123

    # extcodesize check
    zero_address = "0x" + "00" * 20
    with tx_failed():
        d.test(zero_address)

    # now same thing but with create2
    salt = keccak(b"vyper")
    d.test2(f.address, salt)

    test = FooContract(d.created_address())
    assert env.get_code(test.address) == expected_runtime_code
    assert test.foo() == 123

    # check if the create2 address matches our offchain calculation
    initcode = env.get_code(f.address)
    initcode = initcode[len(ERC5202_PREFIX) :]  # strip the prefix
    assert HexBytes(test.address) == create2_address_of(d.address, salt, initcode)

    # can't collide addresses
    with tx_failed():
        d.test2(f.address, salt)


def test_create_from_blueprint_bad_code_offset(
    get_contract, get_contract_from_ir, deploy_blueprint_for, env, tx_failed
):
    deployer_code = """
BLUEPRINT: immutable(address)

@deploy
def __init__(blueprint_address: address):
    BLUEPRINT = blueprint_address

@external
def test(code_ofst: uint256) -> address:
    return create_from_blueprint(BLUEPRINT, code_offset=code_ofst)
    """

    initcode_len = 100

    # deploy a blueprint contract whose contained initcode contains only
    # zeroes (so no matter which offset, create_from_blueprint will
    # return empty code)
    ir = IRnode.from_list(["deploy", 0, ["seq"] + ["stop"] * initcode_len, 0])
    bytecode, _ = compile_ir.assembly_to_evm(
        compile_ir.compile_to_assembly(ir, optimize=OptimizationLevel.NONE)
    )
    # manually deploy the bytecode
    c = env.deploy(abi=[], bytecode=bytecode)
    blueprint_address = c.address

    d = get_contract(deployer_code, blueprint_address)

    # deploy with code_ofst=0 fine
    d.test(0)

    # deploy with code_ofst=len(blueprint) - 1 fine
    d.test(initcode_len - 1)

    # code_offset=len(blueprint) NOT fine! would EXTCODECOPY empty initcode
    with tx_failed():
        d.test(initcode_len)

    # code_offset=EIP_170_LIMIT definitely not fine!
    with tx_failed():
        d.test(EIP_170_LIMIT)


# test create_from_blueprint with args
def test_create_from_blueprint_args(
    get_contract, deploy_blueprint_for, env, keccak, create2_address_of, tx_failed
):
    code = """
struct Bar:
    x: String[32]

FOO: immutable(String[128])
BAR: immutable(Bar)

@deploy
def __init__(foo: String[128], bar: Bar):
    FOO = foo
    BAR = bar

@external
def foo() -> String[128]:
    return FOO

@external
def bar() -> Bar:
    return BAR
    """

    deployer_code = """
struct Bar:
    x: String[32]

created_address: public(address)

@external
def test(target: address, arg1: String[128], arg2: Bar):
    self.created_address = create_from_blueprint(target, arg1, arg2)

@external
def test2(target: address, arg1: String[128], arg2: Bar, salt: bytes32):
    self.created_address = create_from_blueprint(target, arg1, arg2, salt=salt)

@external
def test3(target: address, argdata: Bytes[1024]):
    self.created_address = create_from_blueprint(target, argdata, raw_args=True)

@external
def test4(target: address, argdata: Bytes[1024], salt: bytes32):
    self.created_address = create_from_blueprint(target, argdata, salt=salt, raw_args=True)

@external
def should_fail(target: address, arg1: String[129], arg2: Bar):
    self.created_address = create_from_blueprint(target, arg1, arg2)
    """
    FOO = "hello!"
    BAR = ("world!",)

    # deploy a foo so we can compare its bytecode with factory deployed version
    foo_contract = get_contract(code, FOO, BAR)
    expected_runtime_code = env.get_code(foo_contract.address)

    f, FooContract = deploy_blueprint_for(code)

    d = get_contract(deployer_code)

    initcode = env.get_code(f.address)[3:]

    d.test(f.address, FOO, BAR)

    test = FooContract(d.created_address())
    assert env.get_code(test.address) == expected_runtime_code
    assert test.foo() == FOO
    assert test.bar() == BAR

    # extcodesize check
    with tx_failed():
        d.test("0x" + "00" * 20, FOO, BAR)

    # now same thing but with create2
    salt = keccak(b"vyper")
    d.test2(f.address, FOO, BAR, salt)

    test = FooContract(d.created_address())
    assert env.get_code(test.address) == expected_runtime_code
    assert test.foo() == FOO
    assert test.bar() == BAR

    encoded_args = abi.encode("(string,(string))", (FOO, BAR))
    assert HexBytes(test.address) == create2_address_of(d.address, salt, initcode + encoded_args)

    d.test3(f.address, encoded_args)
    test = FooContract(d.created_address())
    assert env.get_code(test.address) == expected_runtime_code
    assert test.foo() == FOO
    assert test.bar() == BAR

    d.test4(f.address, encoded_args, keccak(b"test4"))
    test = FooContract(d.created_address())
    assert env.get_code(test.address) == expected_runtime_code
    assert test.foo() == FOO
    assert test.bar() == BAR

    # can't collide addresses
    with tx_failed():
        d.test2(f.address, FOO, BAR, salt)
    # ditto - with raw_args
    with tx_failed():
        d.test4(f.address, encoded_args, salt)

    # but creating a contract with different args is ok
    FOO = "bar"
    d.test2(f.address, FOO, BAR, salt)
    # just for kicks
    assert FooContract(d.created_address()).foo() == FOO
    assert FooContract(d.created_address()).bar() == BAR

    # Foo constructor should fail
    FOO = "01" * 129
    BAR = ("",)
    sig = keccak("should_fail(address,string,(string))".encode()).hex()[:10]
    encoded = abi.encode("(address,string,(string))", (f.address, FOO, BAR)).hex()
    with tx_failed():
        env.message_call(d.address, env.deployer, f"{sig}{encoded}")


@pytest.mark.parametrize("revert_on_failure", [True, False, None])
def test_create_copy_of(
    get_contract, env, keccak, create2_address_of, tx_failed, revert_on_failure
):
    revert_arg = "" if revert_on_failure is None else f", revert_on_failure={revert_on_failure}"
    code = f"""
created_address: public(address)
@internal
def _create_copy_of(target: address):
    self.created_address = create_copy_of(target{revert_arg})

@internal
def _create_copy_of2(target: address, salt: bytes32):
    self.created_address = create_copy_of(target, salt=salt{revert_arg})

@external
def test(target: address) -> address:
    x: uint256 = 0
    self._create_copy_of(target)
    assert x == 0  # check memory not clobbered
    return self.created_address

@external
def test2(target: address, salt: bytes32) -> address:
    x: uint256 = 0
    self._create_copy_of2(target, salt)
    assert x == 0  # check memory not clobbered
    return self.created_address
    """

    c = get_contract(code)
    bytecode = env.get_code(c.address)

    c.test(c.address)
    test1 = c.created_address()
    assert env.get_code(test1) == bytecode

    # extcodesize check
    with tx_failed():
        c.test("0x" + "00" * 20)

    salt = keccak(b"vyper")
    c.test2(c.address, salt)
    test2 = c.created_address()
    assert env.get_code(test2) == bytecode

    assert HexBytes(test2) == create2_address_of(c.address, salt, vyper_initcode(bytecode))

    # can't create2 where contract already exists
    if revert_on_failure is False:
        assert c.test2(c.address, salt) == ZERO_ADDRESS
    else:
        with tx_failed():
            c.test2(c.address, salt)


# XXX: these various tests to check the msize allocator for
# create_copy_of and create_from_blueprint depend on calling convention
# and variables writing to memory. think of ways to make more robust to
# changes in calling convention and memory layout
@pytest.mark.parametrize("blueprint_prefix", [b"", b"\xfe", b"\xfe\71\x00"])
def test_create_from_blueprint_complex_value(
    get_contract, deploy_blueprint_for, env, blueprint_prefix
):
    # check msize allocator does not get trampled by value= kwarg
    code = """
var: uint256

@deploy
@payable
def __init__(x: uint256):
    self.var = x

@external
def foo()-> uint256:
    return self.var
    """

    prefix_len = len(blueprint_prefix)

    some_constant = b"\00" * 31 + b"\x0c"

    deployer_code = f"""
created_address: public(address)
x: constant(Bytes[32]) = {some_constant}

@internal
def foo() -> uint256:
    g:uint256 = 42
    return 3

@external
@payable
def test(target: address):
    self.created_address = create_from_blueprint(
        target,
        x,
        code_offset={prefix_len},
        value=self.foo(),
        raw_args=True
    )
    """

    foo_contract = get_contract(code, 12)
    expected_runtime_code = env.get_code(foo_contract.address)

    f, FooContract = deploy_blueprint_for(code, initcode_prefix=blueprint_prefix)

    d = get_contract(deployer_code)

    env.set_balance(env.deployer, 3)
    d.test(f.address, value=3)

    test = FooContract(d.created_address())
    assert env.get_code(test.address) == expected_runtime_code
    assert test.foo() == 12


@pytest.mark.parametrize("blueprint_prefix", [b"", b"\xfe", b"\xfe\71\x00"])
def test_create_from_blueprint_complex_salt_raw_args(
    get_contract, deploy_blueprint_for, env, blueprint_prefix
):
    # test msize allocator does not get trampled by salt= kwarg
    code = """
var: uint256

@deploy
@payable
def __init__(x: uint256):
    self.var = x

@external
def foo()-> uint256:
    return self.var
    """

    some_constant = b"\00" * 31 + b"\x0c"
    prefix_len = len(blueprint_prefix)

    deployer_code = f"""
created_address: public(address)

x: constant(Bytes[32]) = {some_constant}
salt: constant(bytes32) = keccak256("kebab")

@internal
def foo() -> bytes32:
    g:uint256 = 42
    return salt

@external
@payable
def test(target: address):
    self.created_address = create_from_blueprint(
        target,
        x,
        code_offset={prefix_len},
        salt=self.foo(),
        raw_args= True
    )
    """

    foo_contract = get_contract(code, 12)
    expected_runtime_code = env.get_code(foo_contract.address)

    f, FooContract = deploy_blueprint_for(code, initcode_prefix=blueprint_prefix)

    d = get_contract(deployer_code)

    d.test(f.address)

    test = FooContract(d.created_address())
    assert env.get_code(test.address) == expected_runtime_code
    assert test.foo() == 12


@pytest.mark.parametrize("blueprint_prefix", [b"", b"\xfe", b"\xfe\71\x00"])
def test_create_from_blueprint_complex_salt_no_constructor_args(
    get_contract, deploy_blueprint_for, env, blueprint_prefix
):
    # test msize allocator does not get trampled by salt= kwarg
    code = """
var: uint256

@deploy
@payable
def __init__():
    self.var = 12

@external
def foo()-> uint256:
    return self.var
    """

    prefix_len = len(blueprint_prefix)
    deployer_code = f"""
created_address: public(address)

salt: constant(bytes32) = keccak256("kebab")

@external
@payable
def test(target: address):
    self.created_address = create_from_blueprint(
        target,
        code_offset={prefix_len},
        salt=keccak256(_abi_encode(target))
    )
    """

    foo_contract = get_contract(code)
    expected_runtime_code = env.get_code(foo_contract.address)

    f, FooContract = deploy_blueprint_for(code, initcode_prefix=blueprint_prefix)

    d = get_contract(deployer_code)

    d.test(f.address)

    test = FooContract(d.created_address())
    assert env.get_code(test.address) == expected_runtime_code
    assert test.foo() == 12


def test_blueprint_evals_once_side_effects(get_contract, deploy_blueprint_for, env):
    # test msize allocator does not get trampled by salt= kwarg
    code = """
foo: public(uint256)
    """

    deployer_code = """
created_address: public(address)
deployed: public(uint256)

@external
def get() -> Bytes[32]:
    self.deployed += 1
    return b''

@external
def create_(target: address):
    self.created_address = create_from_blueprint(
        target,
        raw_call(self, method_id("get()"), max_outsize=32),
        raw_args=True, code_offset=3
    )
    """

    foo_contract = get_contract(code)
    expected_runtime_code = env.get_code(foo_contract.address)

    f, FooContract = deploy_blueprint_for(code)

    d = get_contract(deployer_code)

    d.create_(f.address)

    test = FooContract(d.created_address())
    assert env.get_code(test.address) == expected_runtime_code
    assert test.foo() == 0
    assert d.deployed() == 1


def test_create_copy_of_complex_kwargs(get_contract, env):
    # test msize allocator does not get trampled by salt= kwarg
    complex_salt = """
created_address: public(address)

@external
def test(target: address) -> address:
    self.created_address = create_copy_of(
        target,
        salt=keccak256(_abi_encode(target))
    )
    return self.created_address

    """

    c = get_contract(complex_salt)
    bytecode = env.get_code(c.address)
    assert bytecode  # Sanity check
    c.test(c.address)
    test1 = c.address
    assert env.get_code(test1) == bytecode

    # test msize allocator does not get trampled by value= kwarg
    complex_value = """
created_address: public(address)

@external
@payable
def test(target: address) -> address:
    value: uint256 = 2
    self.created_address = create_copy_of(target, value = [2,2,2][value])
    return self.created_address

    """

    c = get_contract(complex_value)
    bytecode = env.get_code(c.address)
    env.set_balance(env.deployer, 2)

    c.test(c.address, value=2)
    test1 = c.address
    assert env.get_code(test1) == bytecode


def test_raw_create(get_contract, env):
    to_deploy_code = """
foo: public(uint256)
    """

    out = compile_code(to_deploy_code, output_formats=["bytecode", "bytecode_runtime"])
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))
    runtime = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))

    deployer_code = f"""
@external
def deploy_from_literal() -> address:
    return raw_create({initcode})

@external
def deploy_from_calldata(s: Bytes[1024]) -> address:
    return raw_create(s)

@external
def deploy_from_memory() -> address:
    s: Bytes[1024] = {initcode}
    return raw_create(s)
    """

    deployer = get_contract(deployer_code)

    res = deployer.deploy_from_literal()
    assert env.get_code(res) == runtime

    res = deployer.deploy_from_memory()
    assert env.get_code(res) == runtime

    res = deployer.deploy_from_calldata(initcode)
    assert env.get_code(res) == runtime


def test_raw_create_double_eval(get_contract, env):
    to_deploy_code = """
foo: public(uint256)


@deploy
def __init__(x: uint256):
    self.foo = x
    """

    out = compile_code(to_deploy_code, output_formats=["bytecode", "bytecode_runtime"])
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))
    runtime = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))

    deployer_code = """
interface Foo:
    def foo() -> uint256: view

a: DynArray[uint256, 10]
counter: public(uint256)

@deploy
def __init__():
    self.a.append(1)
    self.a.append(2)

def get_index() -> uint256:
    self.counter += 1
    return 0

@external
def deploy_from_calldata(s: Bytes[1024]) -> address:
    res: address =  raw_create(s, self.a[self.get_index()])
    assert staticcall Foo(res).foo() == 1
    return res
    """

    deployer = get_contract(deployer_code)

    res = deployer.deploy_from_calldata(initcode)
    assert env.get_code(res) == runtime

    assert deployer.counter() == 1


def test_raw_create_salt(get_contract, env, create2_address_of, keccak):
    to_deploy_code = """
foo: public(uint256)

@deploy
def __init__(arg: uint256):
    self.foo = arg
    """

    out = compile_code(to_deploy_code, output_formats=["bytecode", "bytecode_runtime"])
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))
    runtime = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))

    deployer_code = """
@external
def deploy_from_calldata(s: Bytes[1024], arg: uint256, salt: bytes32) -> address:
    return raw_create(s, arg, salt=salt)
    """

    deployer = get_contract(deployer_code)

    salt = keccak(b"vyper")
    arg = 42
    res = deployer.deploy_from_calldata(initcode, arg, salt)

    initcode = initcode + abi.encode("(uint256)", (arg,))

    assert HexBytes(res) == create2_address_of(deployer.address, salt, initcode)

    assert env.get_code(res) == runtime


# test that create_from_blueprint bubbles up revert data
def test_bubble_revert_data_blueprint(get_contract, tx_failed, deploy_blueprint_for):
    ctor_code = """
@deploy
def __init__():
    raise "bad ctor"
    """

    f, _ = deploy_blueprint_for(ctor_code)

    deployer_code = """
@external
def deploy_from_address(t: address) -> address:
    return create_from_blueprint(t)
    """

    deployer = get_contract(deployer_code)

    with tx_failed(exc_text="bad ctor"):
        deployer.deploy_from_address(f.address)


# test that raw_create bubbles up revert data
def test_bubble_revert_data_raw_create(get_contract, tx_failed):
    to_deploy_code = """
@deploy
def __init__():
    raise "bad ctor"
    """

    out = compile_code(to_deploy_code, output_formats=["bytecode"])
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    deployer_code = """
@external
def deploy_from_calldata(s: Bytes[1024]) -> address:
    return raw_create(s)
    """

    deployer = get_contract(deployer_code)

    with tx_failed(exc_text="bad ctor"):
        deployer.deploy_from_calldata(initcode)


# test raw_create with all combinations of value and revert_on_failure kwargs
# (including not present at all)
# additionally parametrize whether the constructor reverts or not
@pytest.mark.parametrize("constructor_reverts", [True, False])
@pytest.mark.parametrize("use_value", [True, False])
@pytest.mark.parametrize("revert_on_failure", [True, False, None])
def test_raw_create_revert_value_kws(
    get_contract, env, tx_failed, constructor_reverts, revert_on_failure, use_value
):
    value = 1
    value_assert = f"assert msg.value == {value}" if use_value else ""
    to_deploy_code = f"""
foo: public(uint256)

@deploy
@payable
def __init__(constructor_reverts: bool):
    assert not constructor_reverts
    {value_assert}
    """

    out = compile_code(to_deploy_code, output_formats=["bytecode", "bytecode_runtime"])
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))
    runtime = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))

    value_kw = f", value={value}" if use_value else ""
    revert_kw = f", revert_on_failure={revert_on_failure}" if revert_on_failure is not None else ""
    deployer_code = f"""
@external
def deploy() -> address:
    return raw_create({initcode},{constructor_reverts}{revert_kw}{value_kw})
    """

    deployer = get_contract(deployer_code)
    env.set_balance(deployer.address, value)

    expect_revert = constructor_reverts and revert_on_failure in (True, None)

    if expect_revert:
        with tx_failed():
            deployer.deploy()
    else:
        res = deployer.deploy()
        if constructor_reverts:
            assert res == ZERO_ADDRESS
            assert env.get_code(res) == b""
        else:
            assert env.get_code(res) == runtime


# test that raw_create correctly interfaces with the abi encoder
# and can handle dynamic arguments
def test_raw_create_dynamic_arg(get_contract, env):
    array = [1, 2, 3]

    to_deploy_code = """
foo: public(uint256)

@deploy
@payable
def __init__(a: DynArray[uint256, 10]):
    for i: uint256 in range(1, 4):
        assert a[i - 1] == i
    """

    out = compile_code(to_deploy_code, output_formats=["bytecode", "bytecode_runtime"])
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))
    runtime = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))

    deployer_code = f"""
@external
def deploy() -> address:
    a: DynArray[uint256, 10] = {array}
    return raw_create({initcode}, a)
    """

    deployer = get_contract(deployer_code)

    res = deployer.deploy()

    assert env.get_code(res) == runtime


@pytest.mark.parametrize("arg", [12, 257, 2**256 - 1])
@pytest.mark.parametrize("length_offset", [-32, -1, 0, 1, 32])
def test_raw_create_change_initcode_size(
    get_contract, deploy_blueprint_for, env, arg, length_offset
):
    to_deploy_code = """
foo: public(uint256)

@deploy
def __init__(arg: uint256):
    self.foo = arg

"""

    out = compile_code(to_deploy_code, output_formats=["bytecode", "bytecode_runtime"])
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))
    runtime = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))

    dummy_bytes = b"\x02" * (len(initcode) + length_offset)

    deployer_code = f"""
x:DynArray[Bytes[1024],1]

@internal
def change_initcode_length(v: Bytes[1024]) -> uint256:
    self.x.pop()
    self.x.append({dummy_bytes})
    return {arg}

@external
def deploy(s: Bytes[1024]) -> address:
    self.x.append(s)
    contract: address = raw_create(self.x[0], self.change_initcode_length(s))
    return contract
"""

    deployer = get_contract(deployer_code)

    res = deployer.deploy(initcode)
    assert env.get_code(res) == runtime

    _, FooContract = deploy_blueprint_for(to_deploy_code)
    res = FooContract(res)

    assert res.foo() == arg


# salt=self.change_code(salt) changes the value at the ptr self.c
# this test checks that the previous evaluation of self.c (the initcode argument) is not
# overwritten by the new value
def test_raw_create_change_value_at_ptr(get_contract, env, create2_address_of, keccak):
    to_deploy_code = """
foo: public(uint256)

@deploy
def __init__(arg: uint256):
    self.foo = arg
    """

    out = compile_code(to_deploy_code, output_formats=["bytecode", "bytecode_runtime"])
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))
    runtime = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))

    deployer_code = """
c: Bytes[1024]

def change_code(salt: bytes32) -> bytes32:
    self.c = b""
    return salt

@external
def deploy_from_calldata(s: Bytes[1024], arg: uint256, salt: bytes32) -> address:
    self.c = s
    return raw_create(self.c, arg, salt=self.change_code(salt))
    """

    deployer = get_contract(deployer_code)

    salt = keccak(b"vyper")
    arg = 42
    res = deployer.deploy_from_calldata(initcode, arg, salt)

    initcode = initcode + abi.encode("(uint256)", (arg,))

    assert HexBytes(res) == create2_address_of(deployer.address, salt, initcode)
    assert env.get_code(res) == runtime


# evaluation of the value kwarg changes the value of the salt kwarg
# value kwarg comes after the salt kwarg in the source code
@pytest.mark.xfail(raises=AssertionError, reason="salt kwarg is evaluated after value kwarg")
def test_raw_create_order_of_eval_of_kwargs(get_contract, env, create2_address_of, keccak):
    to_deploy_code = """
foo: public(uint256)

@deploy
@payable
def __init__(arg: uint256):
    self.foo = arg
    """

    out = compile_code(to_deploy_code, output_formats=["bytecode", "bytecode_runtime"])
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))
    runtime = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))

    deployer_code = """
c: Bytes[1024]
salt: bytes32

def change_salt(value_: uint256) -> uint256:
    self.salt = convert(0x01, bytes32)
    return value_

@external
def deploy_from_calldata(s: Bytes[1024], arg: uint256, salt: bytes32, value_: uint256) -> address:
    self.salt = salt
    return raw_create(s, arg, salt=self.salt, value=self.change_salt(value_))
    """

    deployer = get_contract(deployer_code)
    value = 42
    env.set_balance(deployer.address, value)

    salt = keccak(b"vyper")
    arg = 42
    res = deployer.deploy_from_calldata(initcode, arg, salt, value)

    initcode = initcode + abi.encode("(uint256)", (arg,))

    assert HexBytes(res) == create2_address_of(deployer.address, salt, initcode)
    assert env.get_code(res) == runtime
    assert env.get_balance(res) == value
