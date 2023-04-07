import pytest
import rlp
from eth.codecs import abi
from hexbytes import HexBytes

from vyper.utils import EIP_170_LIMIT, checksum_encode, keccak256


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
    return SubContract(self.other).hello()

    """

    c = get_contract(code)

    assert c.hello() == b"hello world!"
    c.test(transact={})
    assert c.test2() == b"hello world!"


def test_minimal_proxy_exception(w3, get_contract, assert_tx_failed):
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
    return SubContract(self.other).hello(a)
    """

    c = get_contract(code)

    assert c.hello(1) == b"hello world!"
    c.test(transact={})
    assert c.test2(1) == b"hello world!"

    assert_tx_failed(lambda: c.test2(0))

    GAS_SENT = 30000
    tx_hash = c.test2(0, transact={"gas": GAS_SENT})

    receipt = w3.eth.get_transaction_receipt(tx_hash)

    assert receipt["status"] == 0
    assert receipt["gasUsed"] < GAS_SENT


def test_create_minimal_proxy_to_create2(
    get_contract, create2_address_of, keccak, assert_tx_failed
):
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
    assert_tx_failed(lambda: c.test(salt, transact={}))


# test blueprints with various prefixes - 0xfe would block calls to the blueprint
# contract, and 0xfe7100 is ERC5202 magic
@pytest.mark.parametrize("blueprint_prefix", [b"", b"\xfe", b"\xfe\71\x00"])
def test_create_from_blueprint(
    get_contract,
    deploy_blueprint_for,
    w3,
    keccak,
    create2_address_of,
    assert_tx_failed,
    blueprint_prefix,
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
    assert_tx_failed(lambda: d.test(zero_address))

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
    assert_tx_failed(lambda: d.test2(f.address, salt))


def test_create_from_blueprint_bad_code_offset(
    get_contract, get_contract_from_ir, deploy_blueprint_for, w3, assert_tx_failed
):
    deployer_code = """
BLUEPRINT: immutable(address)

@external
def __init__(blueprint_address: address):
    BLUEPRINT = blueprint_address

@external
def test(code_ofst: uint256) -> address:
    return create_from_blueprint(BLUEPRINT, code_offset=code_ofst)
    """

    # use a bunch of JUMPDEST + STOP instructions as blueprint code
    # (as any STOP instruction returns valid code, split up with
    # jumpdests as optimization fence)
    initcode_len = 100
    f = get_contract_from_ir(["deploy", 0, ["seq"] + ["jumpdest", "stop"] * (initcode_len // 2), 0])
    blueprint_code = w3.eth.get_code(f.address)
    print(blueprint_code)

    d = get_contract(deployer_code, f.address)

    # deploy with code_ofst=0 fine
    d.test(0)

    # deploy with code_ofst=len(blueprint) - 1 fine
    d.test(initcode_len - 1)

    # code_offset=len(blueprint) NOT fine! would EXTCODECOPY empty initcode
    assert_tx_failed(lambda: d.test(initcode_len))

    # code_offset=EIP_170_LIMIT definitely not fine!
    assert_tx_failed(lambda: d.test(EIP_170_LIMIT))


# test create_from_blueprint with args
def test_create_from_blueprint_args(
    get_contract, deploy_blueprint_for, w3, keccak, create2_address_of, assert_tx_failed
):
    code = """
struct Bar:
    x: String[32]

FOO: immutable(String[128])
BAR: immutable(Bar)

@external
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

    initcode = w3.eth.get_code(f.address)

    d.test(f.address, FOO, BAR, transact={})

    test = FooContract(d.created_address())
    assert w3.eth.get_code(test.address) == expected_runtime_code
    assert test.foo() == FOO
    assert test.bar() == BAR

    # extcodesize check
    assert_tx_failed(lambda: d.test("0x" + "00" * 20, FOO, BAR))

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
    assert_tx_failed(lambda: d.test2(f.address, FOO, BAR, salt))
    # ditto - with raw_args
    assert_tx_failed(lambda: d.test4(f.address, encoded_args, salt))

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
    assert_tx_failed(lambda: w3.eth.send_transaction({"to": d.address, "data": f"{sig}{encoded}"}))


def test_create_copy_of(get_contract, w3, keccak, create2_address_of, assert_tx_failed):
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
    assert_tx_failed(lambda: c.test("0x" + "00" * 20))

    # test1 = c.test(b"\x01")
    # assert w3.eth.get_code(test1) == b"\x01"

    salt = keccak(b"vyper")
    c.test2(c.address, salt, transact={})
    test2 = c.created_address()
    assert w3.eth.get_code(test2) == bytecode

    assert HexBytes(test2) == create2_address_of(c.address, salt, vyper_initcode(bytecode))

    # can't create2 where contract already exists
    assert_tx_failed(lambda: c.test2(c.address, salt, transact={}))

    # test single byte contract
    # test2 = c.test2(b"\x01", salt)
    # assert HexBytes(test2) == create2_address_of(c.address, salt, vyper_initcode(b"\x01"))
    # assert_tx_failed(lambda: c.test2(bytecode, salt))
