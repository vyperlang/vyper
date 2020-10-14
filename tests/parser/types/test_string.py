import pytest

pytestmark = pytest.mark.usefixtures("memory_mocker")


def test_string_return(get_contract_with_gas_estimation):
    code = """
@external
def testb() -> String[100]:
    a: String[100] = "test return"
    return a

@external
def testa(inp: String[100]) -> String[100]:
    return inp
    """

    c = get_contract_with_gas_estimation(code)

    assert c.testa("meh") == "meh"
    assert c.testb() == "test return"


def test_string_concat(get_contract_with_gas_estimation):
    code = """
@external
def testb(inp: String[10]) -> String[128]:
    a: String[100] = "return message:"
    b: String[128] = concat(a, " ", inp)
    return b

@external
def testa(inp: String[10]) -> String[160]:
    a: String[100] = "<-- return message"
    return concat("Funny ", inp, " ", inp, a)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.testb("bob") == "return message: bob"
    assert c.testa("foo") == "Funny foo foo<-- return message"


def test_basic_long_string_as_keys(get_contract, w3):
    code = """
mapped_string: HashMap[String[34], int128]

@external
def set(k: String[34], v: int128):
    self.mapped_string[k] = v

@external
def get(k: String[34]) -> int128:
    return self.mapped_string[k]
    """

    c = get_contract(code)

    c.set(b"a" * 34, 6789, transact={"gas": 10 ** 6})

    assert c.get(b"a" * 34) == 6789


def test_string_slice(get_contract_with_gas_estimation, assert_tx_failed):
    test_slice4 = """
@external
def foo(inp: String[10], start: uint256, _len: uint256) -> String[10]:
    return slice(inp, start, _len)
    """

    c = get_contract_with_gas_estimation(test_slice4)
    assert c.foo("badminton", 3, 3) == "min"
    assert c.foo("badminton", 0, 9) == "badminton"
    assert c.foo("badminton", 1, 8) == "adminton"
    assert c.foo("badminton", 1, 7) == "adminto"
    assert c.foo("badminton", 1, 0) == ""
    assert c.foo("badminton", 9, 0) == ""

    assert_tx_failed(lambda: c.foo("badminton", 0, 10))
    assert_tx_failed(lambda: c.foo("badminton", 1, 9))
    assert_tx_failed(lambda: c.foo("badminton", 9, 1))
    assert_tx_failed(lambda: c.foo("badminton", 10, 0))


def test_private_string(get_contract_with_gas_estimation):
    private_test_code = """
greeting: public(String[100])

@external
def __init__():
    self.greeting = "Hello "

@internal
def construct(greet: String[100]) -> String[200]:
    return concat(self.greeting, greet)

@external
def hithere(name: String[100]) -> String[200]:
    d: String[200] = self.construct(name)
    return d
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.hithere("bob") == "Hello bob"
    assert c.hithere("alice") == "Hello alice"


def test_logging_extended_string(get_contract_with_gas_estimation, get_logs):
    code = """
event MyLog:
    arg1: int128
    arg2: String[64]
    arg3: int128

@external
def foo():
    log MyLog(667788, 'hellohellohellohellohellohellohellohellohello', 334455)
    """

    c = get_contract_with_gas_estimation(code)
    log = get_logs(c.foo(transact={}), c, "MyLog")

    assert log[0].args.arg1 == 667788
    assert log[0].args.arg2 == "hello" * 9
    assert log[0].args.arg3 == 334455


def test_tuple_return_external_contract_call_string(get_contract_with_gas_estimation):
    contract_1 = """
@external
def out_literals() -> (int128, address, String[10]):
    return 1, 0x0000000000000000000000000000000000000123, "random"
    """

    contract_2 = """
interface Test:
    def out_literals() -> (int128, address, String[10]) : view

@external
def test(addr: address) -> (int128, address, String[10]):
    a: int128 = 0
    b: address = ZERO_ADDRESS
    c: String[10] = ""
    (a, b, c) = Test(addr).out_literals()
    return a, b,c
    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.out_literals() == [1, "0x0000000000000000000000000000000000000123", "random"]
    assert c2.test(c1.address) == [1, "0x0000000000000000000000000000000000000123", "random"]


def test_default_arg_string(get_contract_with_gas_estimation):

    code = """
@external
def test(a: uint256, b: String[50] = "foo") -> Bytes[100]:
    return concat(
        convert(a, bytes32),
        convert(b, Bytes[50])
    )
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test(12345)[-3:] == b"foo"
    assert c.test(12345, "bar")[-3:] == b"bar"


def test_string_equality(get_contract_with_gas_estimation):
    code = """
_compA: String[100]
_compB: String[100]

@external
def equal_true() -> bool:
    compA: String[100] = "The quick brown fox jumps over the lazy dog"
    compB: String[100] = "The quick brown fox jumps over the lazy dog"
    return compA == compB

@external
def equal_false() -> bool:
    compA: String[100] = "The quick brown fox jumps over the lazy dog"
    compB: String[100] = "The quick brown fox jumps over the lazy hog"
    return compA == compB

@external
def not_equal_true() -> bool:
    compA: String[100] = "The quick brown fox jumps over the lazy dog"
    compB: String[100] = "The quick brown fox jumps over the lazy hog"
    return compA != compB

@external
def not_equal_false() -> bool:
    compA: String[100] = "The quick brown fox jumps over the lazy dog"
    compB: String[100] = "The quick brown fox jumps over the lazy dog"
    return compA != compB

@external
def literal_equal_true() -> bool:
    return "The quick brown fox jumps over the lazy dog" == \
    "The quick brown fox jumps over the lazy dog"

@external
def literal_equal_false() -> bool:
    return "The quick brown fox jumps over the lazy dog" == \
    "The quick brown fox jumps over the lazy hog"

@external
def literal_not_equal_true() -> bool:
    return "The quick brown fox jumps over the lazy dog" != \
    "The quick brown fox jumps over the lazy hog"

@external
def literal_not_equal_false() -> bool:
    return "The quick brown fox jumps over the lazy dog" != \
    "The quick brown fox jumps over the lazy dog"

@external
def storage_equal_true() -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    self._compB = "The quick brown fox jumps over the lazy dog"
    return self._compA == self._compB

@external
def storage_equal_false() -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    self._compB = "The quick brown fox jumps over the lazy hog"
    return self._compA == self._compB

@external
def storage_not_equal_true() -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    self._compB = "The quick brown fox jumps over the lazy hog"
    return self._compA != self._compB

@external
def storage_not_equal_false() -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    self._compB = "The quick brown fox jumps over the lazy dog"
    return self._compA != self._compB

@external
def string_compare_equal(str1: String[100], str2: String[100]) -> bool:
    return str1 == str2

@external
def string_compare_not_equal(str1: String[100], str2: String[100]) -> bool:
    return str1 != str2

@external
def compare_passed_storage_equal(str: String[100]) -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    return self._compA == str

@external
def compare_passed_storage_not_equal(str: String[100]) -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    return self._compA != str

@external
def compare_var_storage_equal_true() -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    compB: String[100] = "The quick brown fox jumps over the lazy dog"
    return self._compA == compB

@external
def compare_var_storage_equal_false() -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    compB: String[100] = "The quick brown fox jumps over the lazy hog"
    return self._compA == compB

@external
def compare_var_storage_not_equal_true() -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    compB: String[100] = "The quick brown fox jumps over the lazy hog"
    return self._compA != compB

@external
def compare_var_storage_not_equal_false() -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    compB: String[100] = "The quick brown fox jumps over the lazy dog"
    return self._compA != compB
    """

    c = get_contract_with_gas_estimation(code)
    assert c.equal_true() is True
    assert c.equal_false() is False
    assert c.not_equal_true() is True
    assert c.not_equal_false() is False
    assert c.literal_equal_true() is True
    assert c.literal_equal_false() is False
    assert c.literal_not_equal_true() is True
    assert c.literal_not_equal_false() is False
    assert c.storage_equal_true() is True
    assert c.storage_equal_false() is False
    assert c.storage_not_equal_true() is True
    assert c.storage_not_equal_false() is False

    a = "The quick brown fox jumps over the lazy dog"
    b = "The quick brown fox jumps over the lazy hog"
    assert c.string_compare_equal(a, a) is True
    assert c.string_compare_equal(a, b) is False
    assert c.string_compare_not_equal(b, a) is True
    assert c.string_compare_not_equal(b, b) is False

    assert c.compare_passed_storage_equal(a) is True
    assert c.compare_passed_storage_equal(b) is False
    assert c.compare_passed_storage_not_equal(a) is False
    assert c.compare_passed_storage_not_equal(b) is True

    assert c.compare_var_storage_equal_true() is True
    assert c.compare_var_storage_equal_false() is False
    assert c.compare_var_storage_not_equal_true() is True
    assert c.compare_var_storage_not_equal_false() is False
