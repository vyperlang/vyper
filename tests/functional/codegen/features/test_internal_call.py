import string
from decimal import Decimal

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from vyper.compiler import compile_code
from vyper.exceptions import ArgumentException, CallViolation

pytestmark = pytest.mark.usefixtures("memory_mocker")


def test_selfcall_code(get_contract_with_gas_estimation):
    selfcall_code = """
@internal
def _foo() -> int128:
    return 3

@external
def bar() -> int128:
    return self._foo()
    """

    c = get_contract_with_gas_estimation(selfcall_code)
    assert c.bar() == 3

    print("Passed no-argument self-call test")


def test_selfcall_code_2(get_contract_with_gas_estimation, keccak):
    selfcall_code_2 = """
@internal
def _double(x: int128) -> int128:
    return x * 2

@external
def returnten() -> int128:
    return self._double(5)

@internal
def _hashy(x: bytes32) -> bytes32:
    return keccak256(x)

@external
def return_hash_of_rzpadded_cow() -> bytes32:
    return self._hashy(0x636f770000000000000000000000000000000000000000000000000000000000)
    """

    c = get_contract_with_gas_estimation(selfcall_code_2)
    assert c.returnten() == 10
    assert c.return_hash_of_rzpadded_cow() == keccak(b"cow" + b"\x00" * 29)

    print("Passed single fixed-size argument self-call test")


# test that side-effecting self calls do not get optimized out
def test_selfcall_optimizer(get_contract):
    code = """
counter: uint256

@internal
def increment_counter() -> uint256:
    self.counter += 1
    return self.counter
@external
def foo() -> (uint256, uint256):
    x: uint256 = unsafe_mul(self.increment_counter(), 0)
    return x, self.counter
    """
    c = get_contract(code)
    assert c.foo() == [0, 1]


def test_selfcall_code_3(get_contract_with_gas_estimation, keccak):
    selfcall_code_3 = """
@internal
def _hashy2(x: Bytes[100]) -> bytes32:
    return keccak256(x)

@external
def return_hash_of_cow_x_30() -> bytes32:
    return self._hashy2(b"cowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcow")  # noqa: E501

@internal
def _len(x: Bytes[100]) -> uint256:
    return len(x)

@external
def returnten() -> uint256:
    return self._len(b"badminton!")
    """

    c = get_contract_with_gas_estimation(selfcall_code_3)
    assert c.return_hash_of_cow_x_30() == keccak(b"cow" * 30)
    assert c.returnten() == 10

    print("Passed single variable-size argument self-call test")


def test_selfcall_code_4(get_contract_with_gas_estimation):
    selfcall_code_4 = """
@internal
def _summy(x: int128, y: int128) -> int128:
    return x + y

@internal
def _catty(x: Bytes[5], y: Bytes[5]) -> Bytes[10]:
    return concat(x, y)

@internal
def _slicey1(x: Bytes[10], y: uint256) -> Bytes[10]:
    return slice(x, 0, y)

@internal
def _slicey2(y: uint256, x: Bytes[10]) -> Bytes[10]:
    return slice(x, 0, y)

@external
def returnten() -> int128:
    return self._summy(3, 7)

@external
def return_mongoose() -> Bytes[10]:
    return self._catty(b"mon", b"goose")

@external
def return_goose() -> Bytes[10]:
    return self._slicey1(b"goosedog", 5)

@external
def return_goose2() -> Bytes[10]:
    return self._slicey2(5, b"goosedog")
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

@internal
def _increment():
    self.counter += 1

@external
def returnten() -> int128:
    for i: uint256 in range(10):
        self._increment()
    return self.counter
    """
    c = get_contract_with_gas_estimation(selfcall_code_5)
    assert c.returnten() == 10

    print("Passed self-call statement test")


def test_selfcall_code_6(get_contract_with_gas_estimation):
    selfcall_code_6 = """
excls: Bytes[32]

@internal
def _set_excls(arg: Bytes[32]):
    self.excls = arg

@internal
def _underscore() -> Bytes[1]:
    return b"_"

@internal
def _hardtest(x: Bytes[100], y: uint256, z: uint256, a: Bytes[100], b: uint256, c: uint256) -> Bytes[201]:  # noqa: E501
    return concat(slice(x, y, z), self._underscore(), slice(a, b, c))

@external
def return_mongoose_revolution_32_excls() -> Bytes[201]:
    self._set_excls(b"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    return self._hardtest(b"megamongoose123", 4, 8, concat(b"russian revolution", self.excls), 8, 42)
    """

    c = get_contract_with_gas_estimation(selfcall_code_6)
    assert c.return_mongoose_revolution_32_excls() == b"mongoose_revolution" + b"!" * 32

    print("Passed composite self-call test")


def test_list_call(get_contract_with_gas_estimation):
    code = """
@internal
def _foo0(x: int128[2]) -> int128:
    return x[0]

@internal
def _foo1(x: int128[2]) -> int128:
    return x[1]


@external
def foo1(x: int128[2]) -> int128:
    return self._foo1(x)

@external
def bar() -> int128:
    x: int128[2] = [0, 0]
    return self._foo0(x)

@external
def bar2() -> int128:
    x: int128[2] = [55, 66]
    return self._foo0(x)

@external
def bar3() -> int128:
    x: int128[2] = [55, 66]
    return self._foo1(x)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.bar() == 0
    assert c.foo1([0, 0]) == 0
    assert c.bar2() == 55
    assert c.bar3() == 66


def test_list_storage_call(get_contract_with_gas_estimation):
    code = """
y: int128[2]

@internal
def _foo0(x: int128[2]) -> int128:
    return x[0]

@internal
def _foo1(x: int128[2]) -> int128:
    return x[1]

@external
def set():
    self.y  = [88, 99]

@external
def bar0() -> int128:
    return self._foo0(self.y)

@external
def bar1() -> int128:
    return self._foo1(self.y)
    """

    c = get_contract_with_gas_estimation(code)
    c.set(transact={})
    assert c.bar0() == 88
    assert c.bar1() == 99


def test_multi_arg_list_call(get_contract_with_gas_estimation):
    code = """
@internal
def _foo0(y: decimal, x: int128[2]) -> int128:
    return x[0]

@internal
def _foo1(x: int128[2], y: decimal) -> int128:
    return x[1]

@internal
def _foo2(y: decimal, x: int128[2]) -> decimal:
    return y

@internal
def _foo3(x: int128[2], y: decimal) -> int128:
    return x[0]

@internal
def _foo4(x: int128[2], y: int128[2]) -> int128:
    return y[0]


@external
def foo1(x: int128[2], y: decimal) -> int128:
    return self._foo1(x, y)

@external
def bar() -> int128:
    x: int128[2] = [0, 0]
    return self._foo0(0.3434, x)

# list as second parameter
@external
def bar2() -> int128:
    x: int128[2] = [55, 66]
    return self._foo0(0.01, x)

@external
def bar3() -> decimal:
    x: int128[2] = [88, 77]
    return self._foo2(1.33, x)

# list as first parameter
@external
def bar4() -> int128:
    x: int128[2] = [88, 77]
    return self._foo1(x, 1.33)

@external
def bar5() -> int128:
    x: int128[2] = [88, 77]
    return self._foo3(x, 1.33)

# two lists
@external
def bar6() -> int128:
    x: int128[2] = [88, 77]
    y: int128[2] = [99, 66]
    return self._foo4(x, y)

    """

    c = get_contract_with_gas_estimation(code)
    assert c.bar() == 0
    assert c.foo1([0, 0], Decimal("0")) == 0
    assert c.bar2() == 55
    assert c.bar3() == Decimal("1.33")
    assert c.bar4() == 77
    assert c.bar5() == 88


def test_multi_mixed_arg_list_call(get_contract_with_gas_estimation):
    code = """
@internal
def _fooz(x: int128[2], y: decimal, z: int128[2], a: decimal) -> int128:
    return z[1]

@internal
def _fooa(x: int128[2], y: decimal, z: int128[2], a: decimal) -> decimal:
    return a

@external
def bar() -> (int128, decimal):
    x: int128[2] = [33, 44]
    y: decimal = 55.44
    z: int128[2] = [55, 66]
    a: decimal = 66.77

    return self._fooz(x, y, z, a), self._fooa(x, y, z, a)
    """
    c = get_contract_with_gas_estimation(code)
    assert c.bar() == [66, Decimal("66.77")]


def test_internal_function_multiple_lists_as_args(get_contract_with_gas_estimation):
    code = """
@internal
def _foo(y: int128[2], x: Bytes[5]) -> int128:
    return y[0]

@internal
def _foo2(x: Bytes[5], y: int128[2]) -> int128:
    return y[0]

@external
def bar() -> int128:
    return self._foo([1, 2], b"hello")

@external
def bar2() -> int128:
    return self._foo2(b"hello", [1, 2])
"""

    c = get_contract_with_gas_estimation(code)
    assert c.bar() == 1
    assert c.bar2() == 1


def test_multi_mixed_arg_list_bytes_call(get_contract_with_gas_estimation):
    code = """
@internal
def _fooz(x: int128[2], y: decimal, z: Bytes[11], a: decimal) -> Bytes[11]:
    return z

@internal
def _fooa(x: int128[2], y: decimal, z: Bytes[11], a: decimal) -> decimal:
    return a

@internal
def _foox(x: int128[2], y: decimal, z: Bytes[11], a: decimal) -> int128:
    return x[1]


@external
def bar() -> (Bytes[11], decimal, int128):
    x: int128[2] = [33, 44]
    y: decimal = 55.44
    z: Bytes[11] = b"hello world"
    a: decimal = 66.77

    return self._fooz(x, y, z, a), self._fooa(x, y, z, a), self._foox(x, y, z, a)
    """
    c = get_contract_with_gas_estimation(code)
    assert c.bar() == [b"hello world", Decimal("66.77"), 44]


FAILING_CONTRACTS_CALL_VIOLATION = [
    """
# should not compile - public to public
@external
def bar() -> int128:
    return 1

@external
def foo() -> int128:
    return self.bar()
    """,
    """
# should not compile - internal to external
@external
def bar() -> int128:
    return 1

@internal
def _baz() -> int128:
    return self.bar()

@external
def foo() -> int128:
    return self._baz()
    """,
]


@pytest.mark.parametrize("failing_contract_code", FAILING_CONTRACTS_CALL_VIOLATION)
def test_selfcall_call_violation(failing_contract_code, assert_compile_failed):
    with pytest.raises(CallViolation):
        _ = compile_code(failing_contract_code)


FAILING_CONTRACTS_ARGUMENT_EXCEPTION = [
    """
# expected no args, args given
@internal
def bar() -> int128:
    return 1

@external
def foo() -> int128:
    return self.bar(1)
    """,
    """
# expected args, none given
@internal
def bar(a: int128) -> int128:
    return 1

@external
def foo() -> int128:
    return self.bar()
    """,
    """
# wrong arg count
@internal
def bar(a: int128) -> int128:
    return 1

@external
def foo() -> int128:
    return self.bar(1, 2)
    """,
    """
@internal
def _foo(x: uint256, y: uint256 = 1):
    pass

@external
def foo(x: uint256, y: uint256):
    self._foo(x, y=y)
    """,
]


@pytest.mark.parametrize("failing_contract_code", FAILING_CONTRACTS_ARGUMENT_EXCEPTION)
def test_selfcall_wrong_arg_count(failing_contract_code, assert_compile_failed):
    assert_compile_failed(lambda: compile_code(failing_contract_code), ArgumentException)


FAILING_CONTRACTS_TYPE_MISMATCH = [
    """
# should not compile - value kwarg when calling {0} function
@{0}
def foo():
    pass

@external
def bar():
    self.foo(value=100)
    """,
    """
# should not compile - gas kwarg when calling {0} function
@{0}
def foo():
    pass

@external
def bar():
    self.foo(gas=100)
    """,
    """
# should not compile - arbitrary kwargs when calling {0} function
@{0}
def foo():
    pass

@external
def bar():
    self.foo(baz=100)
    """,
    """
# should not compile - args-as-kwargs to a {0} function
@{0}
def foo(baz: int128):
    pass

@external
def bar():
    self.foo(baz=100)
    """,
]


@pytest.mark.parametrize("failing_contract_code", FAILING_CONTRACTS_TYPE_MISMATCH)
@pytest.mark.parametrize("decorator", ["external", "internal"])
def test_selfcall_kwarg_raises(failing_contract_code, decorator, assert_compile_failed):
    exc = ArgumentException if decorator == "internal" else CallViolation
    with pytest.raises(exc):
        _ = compile_code(failing_contract_code.format(decorator))


@pytest.mark.parametrize("i,ln,s,", [(100, 6, "abcde"), (41, 40, "a" * 34), (57, 70, "z" * 68)])
def test_struct_return_1(get_contract_with_gas_estimation, i, ln, s):
    contract = f"""
struct X:
    x: int128
    y: String[{ln}]
    z: Bytes[{ln}]

@internal
def get_struct_x() -> X:
    return X(x={i}, y="{s}", z=b"{s}")

@external
def test() -> (int128, String[{ln}], Bytes[{ln}]):
    ret: X = self.get_struct_x()
    return ret.x, ret.y, ret.z
    """

    c = get_contract_with_gas_estimation(contract)

    assert c.test() == [i, s, bytes(s, "utf-8")]


def test_dynamically_sized_struct_as_arg(get_contract_with_gas_estimation):
    contract = """
struct X:
    x: uint256
    y: Bytes[6]

@internal
def _foo(x: X) -> Bytes[6]:
    return x.y

@external
def bar() -> Bytes[6]:
    _X: X = X(x=1, y=b"hello")
    return self._foo(_X)
    """

    c = get_contract_with_gas_estimation(contract)

    assert c.bar() == b"hello"


def test_dynamically_sized_struct_as_arg_2(get_contract_with_gas_estimation):
    contract = """
struct X:
    x: uint256
    y: String[6]

@internal
def _foo(x: X) -> String[6]:
    return x.y

@external
def bar() -> String[6]:
    _X: X = X(x=1, y="hello")
    return self._foo(_X)
    """

    c = get_contract_with_gas_estimation(contract)

    assert c.bar() == "hello"


def test_dynamically_sized_struct_member_as_arg(get_contract_with_gas_estimation):
    contract = """
struct X:
    x: uint256
    y: Bytes[6]

@internal
def _foo(s: Bytes[6]) -> Bytes[6]:
    return s

@external
def bar() -> Bytes[6]:
    _X: X = X(x=1, y=b"hello")
    return self._foo(_X.y)
    """

    c = get_contract_with_gas_estimation(contract)

    assert c.bar() == b"hello"


def test_dynamically_sized_struct_member_as_arg_2(get_contract_with_gas_estimation):
    contract = """
struct X:
    x: uint256
    y: String[6]

@internal
def _foo(s: String[6]) -> String[6]:
    return s

@external
def bar() -> String[6]:
    _X: X = X(x=1, y="hello")
    return self._foo(_X.y)
    """

    c = get_contract_with_gas_estimation(contract)

    assert c.bar() == "hello"


# TODO probably want to refactor these into general test utils
st_uint256 = st.integers(min_value=0, max_value=2**256 - 1)
st_string65 = st.text(max_size=65, alphabet=string.printable)
st_bytes65 = st.binary(max_size=65)
st_sarray3 = st.lists(st_uint256, min_size=3, max_size=3)
st_darray3 = st.lists(st_uint256, max_size=3)

internal_call_kwargs_cases = [
    ("uint256", st_uint256),
    ("String[65]", st_string65),
    ("Bytes[65]", st_bytes65),
    ("uint256[3]", st_sarray3),
    ("DynArray[uint256, 3]", st_darray3),
]


@pytest.mark.parametrize("typ1,strategy1", internal_call_kwargs_cases)
@pytest.mark.parametrize("typ2,strategy2", internal_call_kwargs_cases)
def test_internal_call_kwargs(get_contract, typ1, strategy1, typ2, strategy2):
    # GHSA-ph9x-4vc9-m39g

    @given(kwarg1=strategy1, default1=strategy1, kwarg2=strategy2, default2=strategy2)
    @settings(max_examples=5)  # len(cases) * len(cases) * 5 * 5
    def fuzz(kwarg1, kwarg2, default1, default2):
        code = f"""
@internal
def foo(a: {typ1} = {repr(default1)}, b: {typ2} = {repr(default2)}) -> ({typ1}, {typ2}):
    return a, b

@external
def test0() -> ({typ1}, {typ2}):
    return self.foo()

@external
def test1() -> ({typ1}, {typ2}):
    return self.foo({repr(kwarg1)})

@external
def test2() -> ({typ1}, {typ2}):
    return self.foo({repr(kwarg1)}, {repr(kwarg2)})

@external
def test3(x1: {typ1}) -> ({typ1}, {typ2}):
    return self.foo(x1)

@external
def test4(x1: {typ1}, x2: {typ2}) -> ({typ1}, {typ2}):
    return self.foo(x1, x2)
        """
        c = get_contract(code)
        assert c.test0() == [default1, default2]
        assert c.test1() == [kwarg1, default2]
        assert c.test2() == [kwarg1, kwarg2]
        assert c.test3(kwarg1) == [kwarg1, default2]
        assert c.test4(kwarg1, kwarg2) == [kwarg1, kwarg2]

    fuzz()
