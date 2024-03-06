import pytest
import rlp
from eth.codecs import abi
from hexbytes import HexBytes

import vyper.ir.compile_ir as compile_ir
from vyper.codegen.ir_node import IRnode
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


def test_create_minimal_proxy_to_call(get_contract, w3):
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
    c.test(transact={})
    assert c.test2() == b"hello world!"


def test_minimal_proxy_exception(w3, get_contract, tx_failed):
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
    c.test(transact={})
    assert c.test2(1) == b"hello world!"

    with tx_failed():
        c.test2(0)

    GAS_SENT = 30000
    tx_hash = c.test2(0, transact={"gas": GAS_SENT})

    receipt = w3.eth.get_transaction_receipt(tx_hash)

    assert receipt["status"] == 0
    assert receipt["gasUsed"] < GAS_SENT


def test_create_minimal_proxy_to_create2(get_contract, create2_address_of, keccak, tx_failed):
    code = """
main: address

@external
def test(_salt: bytes32) -> address:
    self.main = create_minimal_proxy_to(self, salt=_salt)
    return self.main
    """

    c = get_contract(code)

    salt = keccak(b"vyper")
    assert HexBytes(c.test(salt)) == create2_address_of(
        c.address, salt, eip1167_initcode(c.address)
    )

    c.test(salt, transact={})
    # revert on collision
    with tx_failed():
        c.test(salt, transact={})


# test blueprints with various prefixes - 0xfe would block calls to the blueprint
# contract, and 0xfe7100 is ERC5202 magic
@pytest.mark.parametrize("blueprint_prefix", [b"", b"\xfe", ERC5202_PREFIX])
def test_create_from_blueprint(
    get_contract, deploy_blueprint_for, w3, keccak, create2_address_of, tx_failed, blueprint_prefix
):
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
    self.created_address = create_from_blueprint(target, code_offset={prefix_len})

@external
def test2(target: address, salt: bytes32):
    self.created_address = create_from_blueprint(target, code_offset={prefix_len}, salt=salt)
    """

    # deploy a foo so we can compare its bytecode with factory deployed version
    foo_contract = get_contract(code)
    expected_runtime_code = w3.eth.get_code(foo_contract.address)

    f, FooContract = deploy_blueprint_for(code, initcode_prefix=blueprint_prefix)

    d = get_contract(deployer_code)

    d.test(f.address, transact={})

    test = FooContract(d.created_address())
    assert w3.eth.get_code(test.address) == expected_runtime_code
    assert test.foo() == 123

    # extcodesize check
    zero_address = "0x" + "00" * 20
    with tx_failed():
        d.test(zero_address)

    # now same thing but with create2
    salt = keccak(b"vyper")
    d.test2(f.address, salt, transact={})

    test = FooContract(d.created_address())
    assert w3.eth.get_code(test.address) == expected_runtime_code
    assert test.foo() == 123

    # check if the create2 address matches our offchain calculation
    initcode = w3.eth.get_code(f.address)
    initcode = initcode[len(blueprint_prefix) :]  # strip the prefix
    assert HexBytes(test.address) == create2_address_of(d.address, salt, initcode)

    # can't collide addresses
    with tx_failed():
        d.test2(f.address, salt)


# test blueprints with 0xfe7100 prefix, which is the EIP 5202 standard.
# code offset by default should be 3 here.
def test_create_from_blueprint_default_offset(
    get_contract, deploy_blueprint_for, w3, keccak, create2_address_of, tx_failed
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
    expected_runtime_code = w3.eth.get_code(foo_contract.address)

    f, FooContract = deploy_blueprint_for(code)

    d = get_contract(deployer_code)

    d.test(f.address, transact={})

    test = FooContract(d.created_address())
    assert w3.eth.get_code(test.address) == expected_runtime_code
    assert test.foo() == 123

    # extcodesize check
    zero_address = "0x" + "00" * 20
    with tx_failed():
        d.test(zero_address)

    # now same thing but with create2
    salt = keccak(b"vyper")
    d.test2(f.address, salt, transact={})

    test = FooContract(d.created_address())
    assert w3.eth.get_code(test.address) == expected_runtime_code
    assert test.foo() == 123

    # check if the create2 address matches our offchain calculation
    initcode = w3.eth.get_code(f.address)
    initcode = initcode[len(ERC5202_PREFIX) :]  # strip the prefix
    assert HexBytes(test.address) == create2_address_of(d.address, salt, initcode)

    # can't collide addresses
    with tx_failed():
        d.test2(f.address, salt)


def test_create_from_blueprint_bad_code_offset(
    get_contract, get_contract_from_ir, deploy_blueprint_for, w3, tx_failed
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
    c = w3.eth.contract(abi=[], bytecode=bytecode)
    deploy_transaction = c.constructor()
    tx_info = {"from": w3.eth.accounts[0], "value": 0, "gasPrice": 0}
    tx_hash = deploy_transaction.transact(tx_info)
    blueprint_address = w3.eth.get_transaction_receipt(tx_hash)["contractAddress"]

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
    get_contract, deploy_blueprint_for, w3, keccak, create2_address_of, tx_failed
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
    expected_runtime_code = w3.eth.get_code(foo_contract.address)

    f, FooContract = deploy_blueprint_for(code)

    d = get_contract(deployer_code)

    initcode = w3.eth.get_code(f.address)[3:]

    d.test(f.address, FOO, BAR, transact={})

    test = FooContract(d.created_address())
    assert w3.eth.get_code(test.address) == expected_runtime_code
    assert test.foo() == FOO
    assert test.bar() == BAR

    # extcodesize check
    with tx_failed():
        d.test("0x" + "00" * 20, FOO, BAR)

    # now same thing but with create2
    salt = keccak(b"vyper")
    d.test2(f.address, FOO, BAR, salt, transact={})

    test = FooContract(d.created_address())
    assert w3.eth.get_code(test.address) == expected_runtime_code
    assert test.foo() == FOO
    assert test.bar() == BAR

    encoded_args = abi.encode("(string,(string))", (FOO, BAR))
    assert HexBytes(test.address) == create2_address_of(d.address, salt, initcode + encoded_args)

    d.test3(f.address, encoded_args, transact={})
    test = FooContract(d.created_address())
    assert w3.eth.get_code(test.address) == expected_runtime_code
    assert test.foo() == FOO
    assert test.bar() == BAR

    d.test4(f.address, encoded_args, keccak(b"test4"), transact={})
    test = FooContract(d.created_address())
    assert w3.eth.get_code(test.address) == expected_runtime_code
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
    d.test2(f.address, FOO, BAR, salt, transact={})
    # just for kicks
    assert FooContract(d.created_address()).foo() == FOO
    assert FooContract(d.created_address()).bar() == BAR

    # Foo constructor should fail
    FOO = "01" * 129
    BAR = ("",)
    sig = keccak("should_fail(address,string,(string))".encode()).hex()[:10]
    encoded = abi.encode("(address,string,(string))", (f.address, FOO, BAR)).hex()
    with tx_failed():
        w3.eth.send_transaction({"to": d.address, "data": f"{sig}{encoded}"})


def test_create_copy_of(get_contract, w3, keccak, create2_address_of, tx_failed):
    code = """
created_address: public(address)
@internal
def _create_copy_of(target: address):
    self.created_address = create_copy_of(target)

@internal
def _create_copy_of2(target: address, salt: bytes32):
    self.created_address = create_copy_of(target, salt=salt)

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
    bytecode = w3.eth.get_code(c.address)

    c.test(c.address, transact={})
    test1 = c.created_address()
    assert w3.eth.get_code(test1) == bytecode

    # extcodesize check
    with tx_failed():
        c.test("0x" + "00" * 20)

    # test1 = c.test(b"\x01")
    # assert w3.eth.get_code(test1) == b"\x01"

    salt = keccak(b"vyper")
    c.test2(c.address, salt, transact={})
    test2 = c.created_address()
    assert w3.eth.get_code(test2) == bytecode

    assert HexBytes(test2) == create2_address_of(c.address, salt, vyper_initcode(bytecode))

    # can't create2 where contract already exists
    with tx_failed():
        c.test2(c.address, salt, transact={})

    # test single byte contract
    # test2 = c.test2(b"\x01", salt)
    # assert HexBytes(test2) == create2_address_of(c.address, salt, vyper_initcode(b"\x01"))
    # with tx_failed():
    #     c.test2(bytecode, salt)


# XXX: these various tests to check the msize allocator for
# create_copy_of and create_from_blueprint depend on calling convention
# and variables writing to memory. think of ways to make more robust to
# changes in calling convention and memory layout
@pytest.mark.parametrize("blueprint_prefix", [b"", b"\xfe", b"\xfe\71\x00"])
def test_create_from_blueprint_complex_value(
    get_contract, deploy_blueprint_for, w3, blueprint_prefix
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
    expected_runtime_code = w3.eth.get_code(foo_contract.address)

    f, FooContract = deploy_blueprint_for(code, initcode_prefix=blueprint_prefix)

    d = get_contract(deployer_code)

    d.test(f.address, transact={"value": 3})

    test = FooContract(d.created_address())
    assert w3.eth.get_code(test.address) == expected_runtime_code
    assert test.foo() == 12


@pytest.mark.parametrize("blueprint_prefix", [b"", b"\xfe", b"\xfe\71\x00"])
def test_create_from_blueprint_complex_salt_raw_args(
    get_contract, deploy_blueprint_for, w3, blueprint_prefix
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
    expected_runtime_code = w3.eth.get_code(foo_contract.address)

    f, FooContract = deploy_blueprint_for(code, initcode_prefix=blueprint_prefix)

    d = get_contract(deployer_code)

    d.test(f.address, transact={})

    test = FooContract(d.created_address())
    assert w3.eth.get_code(test.address) == expected_runtime_code
    assert test.foo() == 12


@pytest.mark.parametrize("blueprint_prefix", [b"", b"\xfe", b"\xfe\71\x00"])
def test_create_from_blueprint_complex_salt_no_constructor_args(
    get_contract, deploy_blueprint_for, w3, blueprint_prefix
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
    expected_runtime_code = w3.eth.get_code(foo_contract.address)

    f, FooContract = deploy_blueprint_for(code, initcode_prefix=blueprint_prefix)

    d = get_contract(deployer_code)

    d.test(f.address, transact={})

    test = FooContract(d.created_address())
    assert w3.eth.get_code(test.address) == expected_runtime_code
    assert test.foo() == 12


def test_create_copy_of_complex_kwargs(get_contract, w3):
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
    bytecode = w3.eth.get_code(c.address)
    c.test(c.address, transact={})
    test1 = c.created_address()
    assert w3.eth.get_code(test1) == bytecode

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
    bytecode = w3.eth.get_code(c.address)

    c.test(c.address, transact={"value": 2})
    test1 = c.created_address()
    assert w3.eth.get_code(test1) == bytecode
