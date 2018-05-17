from decimal import Decimal
from vyper.exceptions import StructureException


def test_selfcall_code(get_contract_with_gas_estimation):
    selfcall_code = """
@public
def foo() -> int128:
    return 3

@public
def bar() -> int128:
    return self.foo()
    """

    c = get_contract_with_gas_estimation(selfcall_code)
    assert c.bar() == 3

    print("Passed no-argument self-call test")


def test_selfcall_code_2(get_contract_with_gas_estimation, keccak):
    selfcall_code_2 = """
@public
def double(x: int128) -> int128:
    return x * 2

@public
def returnten() -> int128:
    return self.double(5)

@public
def _hashy(x: bytes32) -> bytes32:
    return sha3(x)

@public
def return_hash_of_rzpadded_cow() -> bytes32:
    return self._hashy(0x636f770000000000000000000000000000000000000000000000000000000000)
    """

    c = get_contract_with_gas_estimation(selfcall_code_2)
    assert c.returnten() == 10
    assert c.return_hash_of_rzpadded_cow() == keccak(b'cow' + b'\x00' * 29)

    print("Passed single fixed-size argument self-call test")


def test_selfcall_code_3(get_contract_with_gas_estimation, keccak):
    selfcall_code_3 = """
@public
def _hashy2(x: bytes[100]) -> bytes32:
    return sha3(x)

@public
def return_hash_of_cow_x_30() -> bytes32:
    return self._hashy2("cowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcow")

@public
def _len(x: bytes[100]) -> int128:
    return len(x)

@public
def returnten() -> int128:
    return self._len("badminton!")
    """

    c = get_contract_with_gas_estimation(selfcall_code_3)
    assert c.return_hash_of_cow_x_30() == keccak(b'cow' * 30)
    assert c.returnten() == 10

    print("Passed single variable-size argument self-call test")


def test_selfcall_code_4(get_contract_with_gas_estimation):
    selfcall_code_4 = """
@public
def summy(x: int128, y: int128) -> int128:
    return x + y

@public
def catty(x: bytes[5], y: bytes[5]) -> bytes[10]:
    return concat(x, y)

@public
def slicey1(x: bytes[10], y: int128) -> bytes[10]:
    return slice(x, start=0, len=y)

@public
def slicey2(y: int128, x: bytes[10]) -> bytes[10]:
    return slice(x, start=0, len=y)

@public
def returnten() -> int128:
    return self.summy(3, 7)

@public
def return_mongoose() -> bytes[10]:
    return self.catty("mon", "goose")

@public
def return_goose() -> bytes[10]:
    return self.slicey1("goosedog", 5)

@public
def return_goose2() -> bytes[10]:
    return self.slicey2(5, "goosedog")
    """

    c = get_contract_with_gas_estimation(selfcall_code_4)
    assert c.returnten() == 10
    assert c.return_mongoose() == b"mongoose"
    assert c.return_goose() == b"goose"
    assert c.return_goose2() == b"goose"

    print("Passed multi-argument self-call test")


def test_selfcall_code_5(get_contract_with_gas_estimation):
    selfcall_code_5 = """
counter: int128

@public
def increment():
    self.counter += 1

@public
def returnten() -> int128:
    for i in range(10):
        self.increment()
    return self.counter
    """
    c = get_contract_with_gas_estimation(selfcall_code_5)
    assert c.returnten() == 10

    print("Passed self-call statement test")


def test_selfcall_code_6(get_contract_with_gas_estimation):
    selfcall_code_6 = """
excls: bytes[32]

@public
def set_excls(arg: bytes[32]):
    self.excls = arg

@public
def underscore() -> bytes[1]:
    return "_"

@public
def hardtest(x: bytes[100], y: int128, z: int128, a: bytes[100], b: int128, c: int128) -> bytes[201]:
    return concat(slice(x, start=y, len=z), self.underscore(), slice(a, start=b, len=c))

@public
def return_mongoose_revolution_32_excls() -> bytes[201]:
    self.set_excls("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    return self.hardtest("megamongoose123", 4, 8, concat("russian revolution", self.excls), 8, 42)
    """

    c = get_contract_with_gas_estimation(selfcall_code_6)
    assert c.return_mongoose_revolution_32_excls() == b"mongoose_revolution" + b"!" * 32

    print("Passed composite self-call test")


def test_list_call(get_contract_with_gas_estimation):
    code = """
@public
def foo0(x: int128[2]) -> int128:
    return x[0]

@public
def foo1(x: int128[2]) -> int128:
    return x[1]


@public
def bar() -> int128:
    x: int128[2]
    return self.foo0(x)

@public
def bar2() -> int128:
    x: int128[2] = [55, 66]
    return self.foo0(x)

@public
def bar3() -> int128:
    x: int128[2] = [55, 66]
    return self.foo1(x)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.bar() == 0
    assert c.foo1([0, 0]) == 0
    assert c.bar2() == 55
    assert c.bar3() == 66


def test_list_storage_call(get_contract_with_gas_estimation):
    code = """
y: int128[2]

@public
def foo0(x: int128[2]) -> int128:
    return x[0]

@public
def foo1(x: int128[2]) -> int128:
    return x[1]

@public
def set():
    self.y  = [88, 99]

@public
def bar0() -> int128:
    return self.foo0(self.y)

@public
def bar1() -> int128:
    return self.foo1(self.y)
    """

    c = get_contract_with_gas_estimation(code)
    c.set(transact={})
    assert c.bar0() == 88
    assert c.bar1() == 99


def test_multi_arg_list_call(get_contract_with_gas_estimation):
    code = """
@public
def foo0(y: decimal, x: int128[2]) -> int128:
    return x[0]

@public
def foo1(x: int128[2], y: decimal) -> int128:
    return x[1]

@public
def foo2(y: decimal, x: int128[2]) -> decimal:
    return y

@public
def foo3(x: int128[2], y: decimal) -> int128:
    return x[0]

@public
def foo4(x: int128[2], y: int128[2]) -> int128:
    return y[0]


@public
def bar() -> int128:
    x: int128[2]
    return self.foo0(0.3434, x)

# list as second parameter
@public
def bar2() -> int128:
    x: int128[2] = [55, 66]
    return self.foo0(0.01, x)

@public
def bar3() -> decimal:
    x: int128[2] = [88, 77]
    return self.foo2(1.33, x)

# list as first parameter
@public
def bar4() -> int128:
    x: int128[2] = [88, 77]
    return self.foo1(x, 1.33)

@public
def bar5() -> int128:
    x: int128[2] = [88, 77]
    return self.foo3(x, 1.33)

# two lists
@public
def bar6() -> int128:
    x: int128[2] = [88, 77]
    y: int128[2] = [99, 66]
    return self.foo4(x, y)

    """

    c = get_contract_with_gas_estimation(code)
    assert c.bar() == 0
    assert c.foo1([0, 0], Decimal('0')) == 0
    assert c.bar2() == 55
    assert c.bar3() == Decimal('1.33')
    assert c.bar4() == 77
    assert c.bar5() == 88


def test_multi_mixed_arg_list_call(get_contract_with_gas_estimation):
    code = """
@public
def fooz(x: int128[2], y: decimal, z: int128[2], a: decimal) -> int128:
    return z[1]

@public
def fooa(x: int128[2], y: decimal, z: int128[2], a: decimal) -> decimal:
    return a

@public
def bar() -> (int128, decimal):
    x: int128[2] = [33, 44]
    y: decimal = 55.44
    z: int128[2] = [55, 66]
    a: decimal = 66.77

    return self.fooz(x, y, z, a), self.fooa(x, y, z, a)
    """
    c = get_contract_with_gas_estimation(code)
    assert c.bar() == [66, Decimal('66.77')]


def test_multi_mixed_arg_list_bytes_call(get_contract_with_gas_estimation):
    code = """
@public
def fooz(x: int128[2], y: decimal, z: bytes[11], a: decimal) -> bytes[11]:
    return z

@public
def fooa(x: int128[2], y: decimal, z: bytes[11], a: decimal) -> decimal:
    return a

@public
def foox(x: int128[2], y: decimal, z: bytes[11], a: decimal) -> int128:
    return x[1]

@public
def bar() -> (bytes[11], decimal, int128):
    x: int128[2] = [33, 44]
    y: decimal = 55.44
    z: bytes[11] = "hello world"
    a: decimal = 66.77

    return self.fooz(x, y, z, a), self.fooa(x, y, z, a), self.foox(x, y, z, a)
    """
    c = get_contract_with_gas_estimation(code)
    assert c.bar() == [b"hello world", Decimal('66.77'), 44]


def test_selfcall_with_wrong_arg_count_fails(get_contract_with_gas_estimation, assert_tx_failed):
    code = """
@public
def bar() -> int128:
    return 1

@public
def foo() -> int128:
    return self.bar(1)
"""
    assert_tx_failed(lambda: get_contract_with_gas_estimation(code), StructureException)
