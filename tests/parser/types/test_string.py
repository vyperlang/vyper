
def test_string_return(get_contract_with_gas_estimation):
    code = """
@public
def testb() -> string[100]:
    a: string[100] = "test return"
    return a

@public
def testa(inp: string[100]) -> string[100]:
    return inp
    """

    c = get_contract_with_gas_estimation(code)

    assert c.testa('meh') == "meh"
    assert c.testb() == "test return"


def test_string_concat(get_contract_with_gas_estimation):
    code = """
@public
def testb(inp: string[10]) -> string[128]:
    a: string[100] = "return message:"
    b: string[128] = concat(a, " ", inp)
    return b

@public
def testa(inp: string[10]) -> string[160]:
    a: string[100] = "<-- return message"
    return concat("Funny ", inp, " ", inp, a)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.testb('bob') == "return message: bob"
    assert c.testa('foo') == "Funny foo foo<-- return message"


def test_basic_long_string_as_keys(get_contract, w3):
    code = """
mapped_string: map(string[34], int128)

@public
def set(k: string[34], v: int128):
    self.mapped_string[k] = v

@public
def get(k: string[34]) -> int128:
    return self.mapped_string[k]
    """

    c = get_contract(code)

    c.set(b"a" * 34, 6789, transact={'gas': 10**6})

    assert c.get(b"a" * 34) == 6789


def test_string_slice(get_contract_with_gas_estimation, assert_tx_failed):
    test_slice4 = """
@public
def foo(inp: string[10], start: int128, _len: int128) -> string[10]:
    return slice(inp, start=start, len=_len)
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
greeting: public(string[100])

@public
def __init__():
    self.greeting = "Hello "

@private
def construct(greet: string[100]) -> string[200]:
    return concat(self.greeting, greet)

@public
def hithere(name: string[100]) -> string[200]:
    d: string[200] = self.construct(name)
    return d
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.hithere("bob") == "Hello bob"
    assert c.hithere("alice") == "Hello alice"


def test_logging_extended_string(get_contract_with_gas_estimation, get_logs):
    code = """
MyLog: event({arg1: int128, arg2: string[64], arg3: int128})

@public
def foo():
    log.MyLog(667788, 'hellohellohellohellohellohellohellohellohello', 334455)
    """

    c = get_contract_with_gas_estimation(code)
    log = get_logs(c.foo(transact={}), c, 'MyLog')

    assert log[0].args.arg1 == 667788
    assert log[0].args.arg2 == "hello" * 9
    assert log[0].args.arg3 == 334455


def test_tuple_return_external_contract_call_string(get_contract_with_gas_estimation):
    contract_1 = """
@public
def out_literals() -> (int128, address, string[10]):
    return 1, 0x0000000000000000000000000000000000000123, "random"
    """

    contract_2 = """
contract Test:
    def out_literals() -> (int128, address, string[10]) : constant

@public
def test(addr: address) -> (int128, address, string[10]):
    a: int128
    b: address
    c: string[10]
    (a, b, c) = Test(addr).out_literals()
    return a, b,c
    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.out_literals() == [1, "0x0000000000000000000000000000000000000123", "random"]
    assert c2.test(c1.address) == [1, "0x0000000000000000000000000000000000000123", "random"]


def test_default_arg_string(get_contract_with_gas_estimation):

    code = """
@public
def test(a: uint256, b: string[50] = "foo") -> bytes[100]:
    return concat(
        convert(a, bytes32),
        convert(b, bytes[50])
    )
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test(12345)[-3:] == b"foo"
    assert c.test(12345, "bar")[-3:] == b"bar"


def test_string_equality(get_contract_with_gas_estimation):
    code = """
_compA: string[100]
_compB: string[100]

@public
def equal_true() -> bool:
    compA: string[100] = "The quick brown fox jumps over the lazy dog"
    compB: string[100] = "The quick brown fox jumps over the lazy dog"
    return compA == compB

@public
def equal_false() -> bool:
    compA: string[100] = "The quick brown fox jumps over the lazy dog"
    compB: string[100] = "The quick brown fox jumps over the lazy hog"
    return compA == compB

@public
def not_equal_true() -> bool:
    compA: string[100] = "The quick brown fox jumps over the lazy dog"
    compB: string[100] = "The quick brown fox jumps over the lazy hog"
    return compA != compB

@public
def not_equal_false() -> bool:
    compA: string[100] = "The quick brown fox jumps over the lazy dog"
    compB: string[100] = "The quick brown fox jumps over the lazy dog"
    return compA != compB

@public
def literal_equal_true() -> bool:
    return "The quick brown fox jumps over the lazy dog" == \
    "The quick brown fox jumps over the lazy dog"

@public
def literal_equal_false() -> bool:
    return "The quick brown fox jumps over the lazy dog" == \
    "The quick brown fox jumps over the lazy hog"

@public
def literal_not_equal_true() -> bool:
    return "The quick brown fox jumps over the lazy dog" != \
    "The quick brown fox jumps over the lazy hog"

@public
def literal_not_equal_false() -> bool:
    return "The quick brown fox jumps over the lazy dog" != \
    "The quick brown fox jumps over the lazy dog"

@public
def storage_equal_true() -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    self._compB = "The quick brown fox jumps over the lazy dog"
    return self._compA == self._compB

@public
def storage_equal_false() -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    self._compB = "The quick brown fox jumps over the lazy hog"
    return self._compA == self._compB

@public
def storage_not_equal_true() -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    self._compB = "The quick brown fox jumps over the lazy hog"
    return self._compA != self._compB

@public
def storage_not_equal_false() -> bool:
    self._compA = "The quick brown fox jumps over the lazy dog"
    self._compB = "The quick brown fox jumps over the lazy dog"
    return self._compA != self._compB

@public
def string_compare_equal(str1: string[100], str2: string[100]) -> bool:
    return str1 == str2

@public
def string_compare_not_equal(str1: string[100], str2: string[100]) -> bool:
    return str1 != str2
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
