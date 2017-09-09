import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_selfcall_code():
    selfcall_code = """
def foo() -> num:
    return 3

def bar() -> num:
    return self.foo()
    """

    c = get_contract(selfcall_code)
    assert c.bar() == 3

    print("Passed no-argument self-call test")


def test_selfcall_code_2():
    selfcall_code_2 = """
def double(x: num) -> num:
    return x * 2

def returnten() -> num:
    return self.double(5)

def _hashy(x: bytes32) -> bytes32:
    return sha3(x)

def return_hash_of_rzpadded_cow() -> bytes32:
    return self._hashy(0x636f770000000000000000000000000000000000000000000000000000000000)
    """

    c = get_contract(selfcall_code_2)
    assert c.returnten() == 10
    assert c.return_hash_of_rzpadded_cow() == u.sha3(b'cow' + b'\x00' * 29)

    print("Passed single fixed-size argument self-call test")


def test_selfcall_code_3():
    selfcall_code_3 = """
def _hashy2(x: bytes <= 100) -> bytes32:
    return sha3(x)

def return_hash_of_cow_x_30() -> bytes32:
    return self._hashy2("cowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcow")

def _len(x: bytes <= 100) -> num:
    return len(x)

def returnten() -> num:
    return self._len("badminton!")
    """

    c = get_contract(selfcall_code_3)
    assert c.return_hash_of_cow_x_30() == u.sha3(b'cow' * 30)
    assert c.returnten() == 10

    print("Passed single variable-size argument self-call test")


def test_selfcall_code_4():
    selfcall_code_4 = """
def summy(x: num, y: num) -> num:
    return x + y

def catty(x: bytes <= 5, y: bytes <= 5) -> bytes <= 10:
    return concat(x, y)

def slicey1(x: bytes <= 10, y: num) -> bytes <= 10:
    return slice(x, start=0, len=y)

def slicey2(y: num, x: bytes <= 10) -> bytes <= 10:
    return slice(x, start=0, len=y)

def returnten() -> num:
    return self.summy(3, 7)

def return_mongoose() -> bytes <= 10:
    return self.catty("mon", "goose")

def return_goose() -> bytes <= 10:
    return self.slicey1("goosedog", 5)

def return_goose2() -> bytes <= 10:
    return self.slicey2(5, "goosedog")
    """

    c = get_contract(selfcall_code_4)
    assert c.returnten() == 10
    assert c.return_mongoose() == b"mongoose"
    assert c.return_goose() == b"goose"
    assert c.return_goose2() == b"goose"

    print("Passed multi-argument self-call test")


def test_selfcall_code_5():
    selfcall_code_5 = """
counter: num

def increment():
    self.counter += 1

def returnten() -> num:
    for i in range(10):
        self.increment()
    return self.counter
    """
    c = get_contract(selfcall_code_5)
    assert c.returnten() == 10

    print("Passed self-call statement test")


def test_selfcall_code_6():
    selfcall_code_6 = """
excls: bytes <= 32

def set_excls(arg: bytes <= 32):
    self.excls = arg

def underscore() -> bytes <= 1:
    return "_"

def hardtest(x: bytes <= 100, y: num, z: num, a: bytes <= 100, b: num, c: num) -> bytes <= 201:
    return concat(slice(x, start=y, len=z), self.underscore(), slice(a, start=b, len=c))

def return_mongoose_revolution_32_excls() -> bytes <= 201:
    self.set_excls("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    return self.hardtest("megamongoose123", 4, 8, concat("russian revolution", self.excls), 8, 42)
    """

    c = get_contract(selfcall_code_6)
    assert c.return_mongoose_revolution_32_excls() == b"mongoose_revolution" + b"!" * 32

    print("Passed composite self-call test")
