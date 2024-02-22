import itertools

import pytest

from vyper.compiler import compile_code
from vyper.exceptions import (
    ArgumentException,
    ArrayIndexException,
    ImmutableViolation,
    OverflowException,
    StateAccessViolation,
    TypeMismatch,
)


def test_list_tester_code(get_contract_with_gas_estimation):
    list_tester_code = """
z: DynArray[int128, 3]
z2: DynArray[DynArray[int128, 2], 2]
z3: DynArray[int128, 2]

@external
def foo(x: DynArray[int128, 3]) -> int128:
    return x[0] + x[1] + x[2]

@external
def goo(x: DynArray[DynArray[int128, 2], 2]) -> int128:
    return x[0][0] + x[0][1] + x[1][0] * 10 + x[1][1] * 10

@external
def hoo(x: DynArray[int128, 3]) -> int128:
    y: DynArray[int128, 3] = x
    return y[0] + x[1] + y[2]

@external
def joo(x: DynArray[DynArray[int128, 2], 2]) -> int128:
    y: DynArray[DynArray[int128, 2], 2] = x
    y2: DynArray[int128, 2] = x[1]
    return y[0][0] + y[0][1] + y2[0] * 10 + y2[1] * 10

@external
def koo(x: DynArray[int128, 3]) -> int128:
    self.z = x
    return self.z[0] + x[1] + self.z[2]

@external
def loo(x: DynArray[DynArray[int128, 2], 2]) -> int128:
    self.z2 = x
    self.z3 = x[1]
    return self.z2[0][0] + self.z2[0][1] + self.z3[0] * 10 + self.z3[1] * 10
    """

    c = get_contract_with_gas_estimation(list_tester_code)
    assert c.foo([3, 4, 5]) == 12
    assert c.goo([[1, 2], [3, 4]]) == 73
    assert c.hoo([3, 4, 5]) == 12
    assert c.joo([[1, 2], [3, 4]]) == 73
    assert c.koo([3, 4, 5]) == 12
    assert c.loo([[1, 2], [3, 4]]) == 73
    print("Passed list tests")


def test_string_list(get_contract):
    code = """
@external
def foo1(x: DynArray[String[32], 2]) -> DynArray[String[32], 2]:
    return x

@external
def foo2(x: DynArray[DynArray[String[32], 2], 2]) -> DynArray[DynArray[String[32], 2], 2]:
    return x

@external
def foo3(x: DynArray[DynArray[String[32], 2], 2]) -> DynArray[String[32], 2]:
    return x[0]

@external
def foo4(x: DynArray[DynArray[String[32], 2], 2]) -> String[32]:
    return x[0][0]

@external
def foo5() -> DynArray[String[32], 2]:
    ret: DynArray[String[32], 2] = ["hello"]
    ret.append("world")
    return ret

@external
def foo6() -> DynArray[DynArray[String[32], 2], 2]:
    ret: DynArray[DynArray[String[32], 2], 2] = []
    ret.append(["hello", "world"])
    return ret
    """

    c = get_contract(code)
    assert c.foo1(["hello", "world"]) == ["hello", "world"]
    assert c.foo2([["hello", "world"]]) == [["hello", "world"]]
    assert c.foo3([["hello", "world"]]) == ["hello", "world"]
    assert c.foo4([["hello", "world"]]) == "hello"
    assert c.foo5() == ["hello", "world"]
    assert c.foo6() == [["hello", "world"]]


def test_list_output_tester_code(get_contract_with_gas_estimation):
    list_output_tester_code = """
flag Foobar:
    FOO
    BAR

y: DynArray[Foobar, 2]
z: DynArray[int128, 2]

@external
def foo() -> DynArray[int128, 2]:
    return [3, 5]

@external
def goo() -> DynArray[int128, 2]:
    x: DynArray[int128, 2] = [3, 5]
    return x

@external
def hoo() -> DynArray[int128, 2]:
    self.z = [3, 5]
    return self.z

@external
def hoo1() -> DynArray[int128, 2]:
    self.z = empty(DynArray[int128, 2])
    return self.z

@external
def hoo2() -> DynArray[int128, 2]:
    return empty(DynArray[int128, 2])

@external
def hoo3() -> DynArray[int128, 2]:
    return []

@external
def hoo4() -> DynArray[int128, 2]:
    self.z = []
    return self.z

@external
def hoo5() -> DynArray[DynArray[int128, 2], 2]:
    return []

@external
def joo() -> DynArray[int128, 2]:
    self.z = [3, 5]
    x: DynArray[int128, 2] = self.z
    return x

@external
def koo() -> DynArray[DynArray[int128, 2], 2]:
    return [[1, 2], [3, 4]]

@external
def loo() -> DynArray[DynArray[int128, 2], 2]:
    x: DynArray[DynArray[int128, 2], 2] = [[1, 2], [3, 4]]
    return x

@external
def moo() -> DynArray[DynArray[int128, 2], 2]:
    x: DynArray[int128, 2] = [1,2]
    return [x, [3,4]]

@external
def noo(inp: DynArray[int128, 2]) -> DynArray[int128, 2]:
    return inp

@external
def ooo(inp: DynArray[int128, 2]) -> DynArray[int128, 2]:
    self.z = inp
    return self.z

@external
def poo(inp: DynArray[DynArray[int128, 2], 2]) -> DynArray[DynArray[int128, 2], 2]:
    return inp

@external
def qoo(inp: DynArray[int128, 2]) -> DynArray[DynArray[int128, 2], 2]:
    return [inp, [3,4]]

@external
def roo(inp: DynArray[decimal, 2]) -> DynArray[DynArray[decimal, 2], 2]:
    return [inp, [3.0, 4.0]]

@external
def soo() -> DynArray[Foobar, 2]:
    x: DynArray[Foobar, 2] = [Foobar.FOO, Foobar.BAR]
    return x

@external
def too() -> DynArray[Foobar, 2]:
    self.y = [Foobar.BAR, Foobar.FOO]
    return self.y

@external
def uoo(inp: DynArray[Foobar, 2]) -> DynArray[DynArray[Foobar, 2], 2]:
    return [inp, [Foobar.BAR, Foobar.FOO]]
    """

    c = get_contract_with_gas_estimation(list_output_tester_code)
    assert c.foo() == [3, 5]
    assert c.goo() == [3, 5]
    assert c.hoo() == [3, 5]
    assert c.hoo1() == c.hoo2() == c.hoo3() == c.hoo4() == []
    assert c.hoo5() == []
    assert c.joo() == [3, 5]
    assert c.koo() == [[1, 2], [3, 4]]
    assert c.loo() == [[1, 2], [3, 4]]
    assert c.moo() == [[1, 2], [3, 4]]
    assert c.noo([]) == []
    assert c.noo([3, 5]) == [3, 5]
    assert c.ooo([]) == []
    assert c.ooo([3, 5]) == [3, 5]
    assert c.poo([]) == []
    assert c.poo([[1, 2], [3, 4]]) == [[1, 2], [3, 4]]
    assert c.qoo([1, 2]) == [[1, 2], [3, 4]]
    assert c.roo([1, 2]) == [[1.0, 2.0], [3.0, 4.0]]
    assert c.soo() == [1, 2]
    assert c.too() == [2, 1]
    assert c.uoo([1, 2]) == [[1, 2], [2, 1]]

    print("Passed list output tests")


def test_array_accessor(get_contract_with_gas_estimation):
    array_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: DynArray[int128, 4] = [0, 0, 0, 0]
    a[0] = x
    a[1] = y
    a[2] = z
    a[3] = w
    return a[0] * 1000 + a[1] * 100 + a[2] * 10 + a[3]
    """

    c = get_contract_with_gas_estimation(array_accessor)
    assert c.test_array(2, 7, 1, 8) == 2718
    print("Passed basic array accessor test")


def test_two_d_array_accessor(get_contract_with_gas_estimation):
    two_d_array_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: DynArray[DynArray[int128, 2], 2] = [[0, 0], [0, 0]]
    a[0][0] = x
    a[0][1] = y
    a[1][0] = z
    a[1][1] = w
    return a[0][0] * 1000 + a[0][1] * 100 + a[1][0] * 10 + a[1][1]
    """

    c = get_contract_with_gas_estimation(two_d_array_accessor)
    assert c.test_array(2, 7, 1, 8) == 2718
    print("Passed complex array accessor test")


def test_three_d_array_accessor(get_contract_with_gas_estimation):
    three_d_array_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: DynArray[DynArray[DynArray[int128, 2], 2], 2] = [[[0, 0], [0, 0]], [[0, 0], [0, 0]]]
    a[0][0][0] = x
    a[0][0][1] = y
    a[0][1][0] = z
    a[0][1][1] = w
    a[1][0][0] = -x
    a[1][0][1] = -y
    a[1][1][0] = -z
    a[1][1][1] = -w
    return a[0][0][0] * 1000 + a[0][0][1] * 100 + a[0][1][0] * 10 + a[0][1][1] + \\
        a[1][1][1] * 1000 + a[1][1][0] * 100 + a[1][0][1] * 10 + a[1][0][0]
    """

    c = get_contract_with_gas_estimation(three_d_array_accessor)
    assert c.test_array(2, 7, 1, 8) == -5454


def test_four_d_array_accessor(get_contract_with_gas_estimation):
    four_d_array_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: DynArray[DynArray[DynArray[DynArray[int128, 2], 2], 2], 2] = \\
        [[[[0, 0], [0, 0]], [[0, 0], [0, 0]]], [[[0, 0], [0, 0]], [[0, 0], [0, 0]]]]
    a[0][0][0][0] = x
    a[0][0][0][1] = y
    a[0][0][1][0] = z
    a[0][0][1][1] = w
    a[0][1][0][0] = -x
    a[0][1][0][1] = -y
    a[0][1][1][0] = -z
    a[0][1][1][1] = -w

    a[1][0][0][0] = x + 1
    a[1][0][0][1] = y + 1
    a[1][0][1][0] = z + 1
    a[1][0][1][1] = w + 1
    a[1][1][0][0] = - (x + 1)
    a[1][1][0][1] = - (y + 1)
    a[1][1][1][0] = - (z + 1)
    a[1][1][1][1] = - (w + 1)
    return a[0][0][0][0] * 1000 + a[0][0][0][1] * 100 + a[0][0][1][0] * 10 + a[0][0][1][1] + \\
        a[0][1][1][1] * 1000 + a[0][1][1][0] * 100 + a[0][1][0][1] * 10 + a[0][1][0][0] + \\
        a[1][0][0][0] * 1000 + a[1][0][0][1] * 100 + a[1][0][1][0] * 10 + a[1][0][1][1] + \\
        a[1][1][1][1] * 1000 + a[1][1][1][0] * 100 + a[1][1][0][1] * 10 + a[1][1][0][0]
    """

    c = get_contract_with_gas_estimation(four_d_array_accessor)
    assert c.test_array(2, 7, 1, 8) == -10908


def test_array_negative_accessor(get_contract_with_gas_estimation, assert_compile_failed):
    array_constant_negative_accessor = """
FOO: constant(int128) = -1
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: int128[4] = [0, 0, 0, 0]
    a[0] = x
    a[1] = y
    a[2] = z
    a[3] = w
    return a[-4] * 1000 + a[-3] * 100 + a[-2] * 10 + a[FOO]
    """

    with pytest.raises(ArrayIndexException):
        compile_code(array_constant_negative_accessor)

    array_negative_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: DynArray[int128, 4] = [0, 0, 0, 0]
    a[0] = x
    a[1] = y
    a[2] = z
    a[3] = w
    return a[-4] * 1000 + a[-3] * 100 + a[-2] * 10 + a[-1]
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(array_negative_accessor), ArrayIndexException
    )

    two_d_array_negative_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: DynArray[DynArray[int128, 2], 2] = [[0, 0], [0, 0]]
    a[0][0] = x
    a[0][1] = y
    a[1][0] = z
    a[1][1] = w
    return a[-2][-2] * 1000 + a[-2][-1] * 100 + a[-1][-2] * 10 + a[-1][-1]
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(two_d_array_negative_accessor), ArrayIndexException
    )

    three_d_array_negative_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: DynArray[DynArray[DynArray[int128, 2], 2], 2] = [[[0, 0], [0, 0]], [[0, 0], [0, 0]]]
    a[0][0][0] = x
    a[0][0][1] = y
    a[0][1][0] = z
    a[0][1][1] = w
    a[1][0][0] = -x
    a[1][0][1] = -y
    a[1][1][0] = -z
    a[1][1][1] = -w
    return a[-2][-2][-2] * 1000 + a[-2][-2][-1] * 100 + a[-2][-1][-2] * 10 + a[-2][-1][-1] + \\
        a[-1][-1][-1] * 1000 + a[-1][-1][-2] * 100 + a[-1][-2][-1] * 10 + a[-1][-2][-2]
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(three_d_array_negative_accessor),
        ArrayIndexException,
    )

    four_d_array_negative_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: DynArray[DynArray[DynArray[DynArray[int128, 2], 2], 2], 2] = \\
        [[[[0, 0], [0, 0]], [[0, 0], [0, 0]]], [[[0, 0], [0, 0]], [[0, 0], [0, 0]]]]
    a[0][0][0][0] = x
    a[0][0][0][1] = y
    a[0][0][1][0] = z
    a[0][0][1][1] = w
    a[0][1][0][0] = -x
    a[0][1][0][1] = -y
    a[0][1][1][0] = -z
    a[0][1][1][1] = -w

    a[1][0][0][0] = x + 1
    a[1][0][0][1] = y + 1
    a[1][0][1][0] = z + 1
    a[1][0][1][1] = w + 1
    a[1][1][0][0] = - (x + 1)
    a[1][1][0][1] = - (y + 1)
    a[1][1][1][0] = - (z + 1)
    a[1][1][1][1] = - (w + 1)
    return a[-2][-2][-2][-2] * 1000 + a[-2][-2][-2][-1] * 100 + \\
        a[-2][-2][-1][-2] * 10 + a[-2][-2][-1][-1] + \\
        a[-2][-1][-1][-1] * 1000 + a[-2][-1][-1][-2] * \\
        100 + a[-2][-1][-2][-1] * 10 + a[-2][-1][-2][-2] + \\
        a[-1][-2][-2][-2] * 1000 + a[-1][-2][-2][-1] * \\
        100 + a[-1][-2][-1][-2] * 10 + a[-1][-2][-1][-1] + \\
        a[-1][-1][-1][-1] * 1000 + a[-1][-1][-1][-2] * \\
        100 + a[-1][-1][-2][-1] * 10 + a[-1][-1][-2][-2]
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(four_d_array_negative_accessor),
        ArrayIndexException,
    )


@pytest.mark.parametrize(
    "type,values,false_value",
    [
        ("uint256", [3, 7], 4),
        (
            "address",
            [
                "0x0000000000000000000000000000000000000012",
                "0x0000000000000000000000000000000000000024",
            ],
            "0x0000000000000000000000000000000000000013",
        ),
        ("bool", [True, True], False),
        (
            "bytes32",
            [
                "0x0000000000000000000000000000000000000000000000000000000080ac58cd",
                "0x0000000000000000000000000000000000000000000000000000000080ac58ce",
            ],
            "0x0000000000000000000000000000000000000000000000000000000080ac58cf",
        ),
    ],
)
def test_member_in_list(get_contract_with_gas_estimation, type, values, false_value):
    code = f"""
@external
def check(a: {type}) -> bool:
    x: DynArray[{type}, 2] = [{values[0]}, {values[1]}]
    return a in x
    """
    c = get_contract_with_gas_estimation(code)
    assert c.check(values[0]) is True
    assert c.check(values[1]) is True
    assert c.check(false_value) is False


@pytest.mark.parametrize("type_", ("uint256", "bytes32", "address"))
def test_member_in_empty_list(get_contract_with_gas_estimation, type_):
    code = f"""
@external
def check_in(s: uint128) -> bool:
    a: {type_} = convert(s, {type_})
    x: DynArray[{type_}, 2] = []
    return a in x

@external
def check_not_in(s: uint128) -> bool:
    a: {type_} = convert(s, {type_})
    x: DynArray[{type_}, 2] = []
    return a not in x
    """
    c = get_contract_with_gas_estimation(code)
    for s in (0, 1, 2, 3):
        assert c.check_in(s) is False
        assert c.check_not_in(s) is True


@pytest.mark.parametrize(
    "type,values,false_values",
    [
        ("uint256", [[3, 7], [9, 11]], [4, 10]),
        ("bool", [[True, True], [False, False]], [False, True]),
    ],
)
def test_member_in_nested_list(get_contract_with_gas_estimation, type, values, false_values):
    code = f"""
@external
def check1(a: {type}) -> bool:
    x: DynArray[DynArray[{type}, 2], 2] = {values}
    return a in x[0]

@external
def check2(a: {type}) -> bool:
    x: DynArray[DynArray[{type}, 2], 2] = {values}
    return a in x[1]
    """
    c = get_contract_with_gas_estimation(code)
    assert c.check1(values[0][0]) is True
    assert c.check1(values[0][1]) is True
    assert c.check1(false_values[0]) is False

    assert c.check2(values[1][0]) is True
    assert c.check2(values[1][1]) is True
    assert c.check2(false_values[1]) is False


def test_member_in_nested_address_list(get_contract_with_gas_estimation):
    code = """
@external
def check1(a: address) -> bool:
    x: DynArray[DynArray[address, 2], 2] = [
        [
            0x0000000000000000000000000000000000000012,
            0x0000000000000000000000000000000000000024,
        ],
        [
            0x0000000000000000000000000000000000000036,
            0x0000000000000000000000000000000000000048,
        ],
    ]
    return a in x[0]

@external
def check2(a: address) -> bool:
    x: DynArray[DynArray[address, 2], 2] = [
        [
            0x0000000000000000000000000000000000000012,
            0x0000000000000000000000000000000000000024,
        ],
        [
            0x0000000000000000000000000000000000000036,
            0x0000000000000000000000000000000000000048,
        ],
    ]
    return a in x[1]
    """
    c = get_contract_with_gas_estimation(code)
    assert c.check1("0x0000000000000000000000000000000000000012") is True
    assert c.check1("0x0000000000000000000000000000000000000024") is True
    assert c.check1("0x0000000000000000000000000000000000000036") is False

    assert c.check2("0x0000000000000000000000000000000000000036") is True
    assert c.check2("0x0000000000000000000000000000000000000048") is True
    assert c.check2("0x0000000000000000000000000000000000000024") is False


def test_member_in_nested_bytes32_list(get_contract_with_gas_estimation):
    code = """
@external
def check1(a: bytes32) -> bool:
    x: DynArray[DynArray[bytes32, 2], 2] = [
        [
            0x0000000000000000000000000000000000000000000000000000000080ac58ca,
            0x0000000000000000000000000000000000000000000000000000000080ac58cb,
        ],
        [
            0x0000000000000000000000000000000000000000000000000000000080ac58cc,
            0x0000000000000000000000000000000000000000000000000000000080ac58cd,
        ],
    ]
    return a in x[0]

@external
def check2(a: bytes32) -> bool:
    x: DynArray[DynArray[bytes32, 2], 2] = [
        [
            0x0000000000000000000000000000000000000000000000000000000080ac58ca,
            0x0000000000000000000000000000000000000000000000000000000080ac58cb,
        ],
        [
            0x0000000000000000000000000000000000000000000000000000000080ac58cc,
            0x0000000000000000000000000000000000000000000000000000000080ac58cd,
        ],
    ]
    return a in x[1]
    """
    c = get_contract_with_gas_estimation(code)
    assert c.check1("0x0000000000000000000000000000000000000000000000000000000080ac58ca") is True
    assert c.check1("0x0000000000000000000000000000000000000000000000000000000080ac58cb") is True
    assert c.check1("0x0000000000000000000000000000000000000000000000000000000080ac58cc") is False

    assert c.check2("0x0000000000000000000000000000000000000000000000000000000080ac58cc") is True
    assert c.check2("0x0000000000000000000000000000000000000000000000000000000080ac58cd") is True
    assert c.check2("0x0000000000000000000000000000000000000000000000000000000080ac58ca") is False


def test_member_in_updated_list(get_contract_with_gas_estimation):
    code = """
@external
def foo() -> bool:
    xs: DynArray[uint256, 3] = [2, 2, 2]
    xs = [1, 1]
    y: uint256 = 2
    return y in xs
    """
    c = get_contract_with_gas_estimation(code)
    assert c.foo() is False


def test_member_in_updated_nested_list(get_contract_with_gas_estimation):
    code = """
@external
def foo() -> bool:
    xs: DynArray[DynArray[DynArray[uint256, 3], 3], 3] = [
        [[2, 2, 2], [2, 2, 2], [2, 2, 2]],
        [[2, 2, 2], [2, 2, 2], [2, 2, 2]],
        [[2, 2, 2], [2, 2, 2], [2, 2, 2]],
    ]
    xs = [
        [[1, 1], [1, 1], [1, 1]],
        [[1, 1], [1, 1], [1, 1]],
        [[1, 1], [1, 1], [1, 1]],
    ]
    y: uint256 = 2
    return y in xs[0][0] or y in xs[0][1] or y in xs[0][2] or \\
        y in xs[1][0] or y in xs[1][1] or y in xs[1][2] or \\
        y in xs[2][0] or y in xs[2][1] or y in xs[2][2]
    """
    c = get_contract_with_gas_estimation(code)
    assert c.foo() is False


def test_member_in_list_lhs_side_effects(get_contract_with_gas_estimation):
    code = """
_counter: uint256

@internal
def counter() -> uint256:
    self._counter = 1
    return self._counter

@external
def bar() -> bool:
    x: DynArray[uint256, 4] = [2, 2, 2, 2]
    return self.counter() in x
    """
    c = get_contract_with_gas_estimation(code)
    assert c.bar() is False


def test_member_in_nested_list_lhs_side_effects(get_contract_with_gas_estimation):
    code = """
_counter: uint256

@internal
def counter() -> uint256:
    self._counter = 1
    return self._counter

@external
def bar() -> bool:
    x: DynArray[DynArray[DynArray[uint256, 4], 4], 4] = [
        [[2, 2, 2, 2], [2, 2, 2, 2], [2, 2, 2, 2]],
        [[2, 2, 2, 2], [2, 2, 2, 2], [2, 2, 2, 2]],
        [[2, 2, 2, 2], [2, 2, 2, 2], [2, 2, 2, 2]],
    ]
    return self.counter() in x[0][0]
    """
    c = get_contract_with_gas_estimation(code)
    assert c.bar() is False


def test_member_in_list_rhs_side_effects(get_contract_with_gas_estimation):
    code = """
counter: uint256

@internal
def foo() -> DynArray[uint256, 3]:
    self.counter += 1
    return [0,0,0]

@external
def bar() -> uint256:
    self.counter = 0
    t: bool = self.counter in self.foo()
    return self.counter
    """
    c = get_contract_with_gas_estimation(code)
    assert c.bar() == 1


def test_member_in_nested_list_rhs_side_effects(get_contract_with_gas_estimation):
    code = """
counter: uint256

@internal
def foo() -> DynArray[DynArray[DynArray[uint256, 3], 3], 3]:
    self.counter += 1
    return [
        [[0,0,0], [0,0,0], [0,0,0]],
        [[0,0,0], [0,0,0], [0,0,0]],
        [[0,0,0], [0,0,0], [0,0,0]]
    ]

@external
def bar() -> uint256:
    self.counter = 0
    t: bool = self.counter in self.foo()[0][0]
    return self.counter
    """
    c = get_contract_with_gas_estimation(code)
    assert c.bar() == 1


def test_returns_lists(get_contract_with_gas_estimation):
    code = """
@external
def test_array_num_return() -> DynArray[DynArray[int128, 2], 2]:
    a: DynArray[DynArray[int128, 2], 2] = [empty(DynArray[int128, 2]), [3, 4]]
    return a

@external
def test_array_decimal_return1() -> DynArray[DynArray[decimal, 2], 2]:
    a: DynArray[DynArray[decimal, 2], 2] = [[1.0], [3.0, 4.0]]
    return a

@external
def test_array_decimal_return2() -> DynArray[DynArray[decimal, 2], 2]:
    return [[1.0, 2.0]]

@external
def test_array_decimal_return3() -> DynArray[DynArray[decimal, 2], 2]:
    a: DynArray[DynArray[decimal, 2], 2] = [[1.0, 2.0], [3.0]]
    return a
"""

    c = get_contract_with_gas_estimation(code)
    assert c.test_array_num_return() == [[], [3, 4]]
    assert c.test_array_decimal_return1() == [[1.0], [3.0, 4.0]]
    assert c.test_array_decimal_return2() == [[1.0, 2.0]]
    assert c.test_array_decimal_return3() == [[1.0, 2.0], [3.0]]


def test_mult_list(get_contract_with_gas_estimation):
    code = """
nest3: DynArray[DynArray[DynArray[uint256, 2], 2], 2]
nest4: DynArray[DynArray[DynArray[DynArray[uint256, 2], 2], 2], 2]

@external
def test_multi3_1() -> DynArray[DynArray[DynArray[uint256, 2], 2], 2]:
    l: DynArray[DynArray[DynArray[uint256, 2], 2], 2] = [[[0, 0], [0, 4]], [[0, 7], [0, 123]]]
    self.nest3 = l
    return self.nest3

@external
def test_multi3_2() -> DynArray[DynArray[DynArray[uint256, 2], 2], 2]:
    l: DynArray[DynArray[DynArray[uint256, 2], 2], 2] = [[[0, 0], [0, 4]], [[0, 7], [0, 123]]]
    self.nest3 = l
    l = self.nest3
    return l

@external
def test_multi4_1() -> DynArray[DynArray[DynArray[DynArray[uint256, 2], 2], 2], 2]:
    l: DynArray[DynArray[DynArray[DynArray[uint256, 2], 2], 2], 2] = [[[[1, 0], [0, 4]], [[0, 0], [0, 0]]], [[[444, 0], [0, 0]],[[1, 0], [0, 222]]]]  # noqa: E501
    self.nest4 = l
    l = self.nest4
    return l

@external
def test_multi4_2() -> DynArray[DynArray[DynArray[DynArray[uint256, 2], 2], 2], 2]:
    l: DynArray[DynArray[DynArray[DynArray[uint256, 2], 2], 2], 2] = [[[[1, 0], [0, 4]], [[0, 0], [0, 0]]], [[[444, 0], [0, 0]],[[1, 0], [0, 222]]]]  # noqa: E501
    self.nest4 = l
    return self.nest4
    """

    c = get_contract_with_gas_estimation(code)

    nest3 = [[[0, 0], [0, 4]], [[0, 7], [0, 123]]]
    assert c.test_multi3_1() == nest3
    assert c.test_multi3_2() == nest3
    nest4 = [[[[1, 0], [0, 4]], [[0, 0], [0, 0]]], [[[444, 0], [0, 0]], [[1, 0], [0, 222]]]]
    assert c.test_multi4_1() == nest4
    assert c.test_multi4_2() == nest4


def test_uint256_accessor(get_contract_with_gas_estimation, tx_failed):
    code = """
@external
def bounds_check_uint256(xs: DynArray[uint256, 3], ix: uint256) -> uint256:
    return xs[ix]
    """
    c = get_contract_with_gas_estimation(code)
    with tx_failed():
        c.bounds_check_uint256([], 0)

    assert c.bounds_check_uint256([1], 0) == 1
    with tx_failed():
        c.bounds_check_uint256([1], 1)

    assert c.bounds_check_uint256([1, 2, 3], 0) == 1
    assert c.bounds_check_uint256([1, 2, 3], 2) == 3
    with tx_failed():
        c.bounds_check_uint256([1, 2, 3], 3)

    # TODO do bounds checks for nested darrays


@pytest.mark.parametrize("list_", ([], [11], [11, 12], [11, 12, 13]))
def test_dynarray_len(get_contract_with_gas_estimation, tx_failed, list_):
    code = """
@external
def darray_len(xs: DynArray[uint256, 3]) -> uint256:
    return len(xs)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.darray_len(list_) == len(list_)


def test_dynarray_too_large(get_contract_with_gas_estimation, tx_failed):
    code = """
@external
def darray_len(xs: DynArray[uint256, 3]) -> uint256:
    return len(xs)
    """

    c = get_contract_with_gas_estimation(code)
    with tx_failed():
        c.darray_len([1, 2, 3, 4])


def test_int128_accessor(get_contract_with_gas_estimation, tx_failed):
    code = """
@external
def bounds_check_int128(ix: int128) -> uint256:
    xs: DynArray[uint256, 3] = [1,2,3]
    return xs[ix]
    """
    c = get_contract_with_gas_estimation(code)
    assert c.bounds_check_int128(0) == 1
    assert c.bounds_check_int128(2) == 3
    with tx_failed():
        c.bounds_check_int128(3)
    with tx_failed():
        c.bounds_check_int128(-1)


def test_index_exception(get_contract_with_gas_estimation, assert_compile_failed):
    code = """
@external
def fail() -> uint256:
    xs: DynArray[uint256, 3] = [1,2,3]
    return xs[3]
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), ArrayIndexException)

    code = """
@external
def fail() -> uint256:
    xs: DynArray[uint256, 3] = [1,2,3]
    return xs[-1]
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), ArrayIndexException)


def test_compile_time_bounds_check(get_contract_with_gas_estimation, assert_compile_failed):
    code = """
@external
def parse_list_fail():
    xs: DynArray[uint256, 3] = [2**256, 1, 3]
    pass
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), OverflowException)


def test_2d_array_input_1(get_contract):
    code = """
@internal
def test_input(
    arr: DynArray[DynArray[int128, 2], 1], i: int128
) -> (DynArray[DynArray[int128, 2], 1], int128):
    return arr, i

@external
def test_values(
    arr: DynArray[DynArray[int128, 2], 1], i: int128
) -> (DynArray[DynArray[int128, 2], 1], int128):
    return self.test_input(arr, i)
    """

    c = get_contract(code)
    assert c.test_values([[1, 2]], 3) == [[[1, 2]], 3]


def test_2d_array_input_2(get_contract):
    code = """
@internal
def test_input(
    arr: DynArray[DynArray[int128, 2], 3],
    s: String[10]
) -> (DynArray[DynArray[int128, 2], 3], String[10]):
    return arr, s

@external
def test_values(
    arr: DynArray[DynArray[int128, 2], 3],
    s: String[10]
) -> (DynArray[DynArray[int128, 2], 3], String[10]):
    return self.test_input(arr, s)
    """

    c = get_contract(code)
    assert c.test_values([[1, 2], [3, 4], [5, 6]], "abcdef") == [[[1, 2], [3, 4], [5, 6]], "abcdef"]


def test_nested_index_of_returned_array(get_contract):
    code = """
@internal
def inner() -> (int128, int128):
    return 1,2

@external
def outer() -> DynArray[int128, 2]:
    return [333, self.inner()[0]]
    """

    c = get_contract(code)
    assert c.outer() == [333, 1]


def test_nested_calls_inside_arrays(get_contract):
    code = """
@internal
def _foo(a: uint256, b: DynArray[uint256, 2]) -> (uint256, uint256, uint256, uint256, uint256):
    return 1, a, b[0], b[1], 5

@internal
def _foo2() -> uint256:
    a: DynArray[uint256, 10] = [6,7,8,9,10,11,12,13,15,16]
    return 4

@external
def foo() -> (uint256, uint256, uint256, uint256, uint256):
    return self._foo(2, [3, self._foo2()])
    """

    c = get_contract(code)
    assert c.foo() == [1, 2, 3, 4, 5]


def test_nested_calls_inside_arrays_with_index_access(get_contract):
    code = """
@internal
def _foo(
    a: DynArray[uint256, 2],
    b: DynArray[uint256, 2]
) -> (uint256, uint256, uint256, uint256, uint256):
    return a[1]-b[0], 2, a[0]-b[1], 8-b[1], 5

@internal
def _foo2() -> (uint256, uint256):
    a: DynArray[uint256, 10] = [6,7,8,9,10,11,12,13,15,16]
    return a[6], 4

@external
def foo() -> (uint256, uint256, uint256, uint256, uint256):
    return self._foo([7, self._foo2()[0]], [11, self._foo2()[1]])
    """

    c = get_contract(code)
    assert c.foo() == [1, 2, 3, 4, 5]


append_pop_tests = [
    (
        """
my_array: DynArray[uint256, 5]
@external
def foo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    for x: uint256 in xs:
        self.my_array.append(x)
    return self.my_array
    """,
        lambda xs: xs,
    ),
    (
        """
my_array: DynArray[uint256, 5]
some_var: uint256
@external
def foo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    for x: uint256 in xs:
        self.some_var = x
        # test that typechecker for append args works
        self.my_array.append(self.some_var)
    return self.my_array
    """,
        lambda xs: xs,
    ),
    (
        """
my_array: DynArray[uint256, 5]
@external
def foo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    for x: uint256 in xs:
        self.my_array.append(x)
    for x: uint256 in xs:
        self.my_array.pop()
    return self.my_array
    """,
        lambda xs: [],
    ),
    # check order of evaluation.
    (
        """
my_array: DynArray[uint256, 5]
@external
def foo(xs: DynArray[uint256, 5]) -> (DynArray[uint256, 5], uint256):
    for x: uint256 in xs:
        self.my_array.append(x)
    return self.my_array, self.my_array.pop()
    """,
        lambda xs: None if len(xs) == 0 else [xs, xs[-1]],
    ),
    # check order of evaluation.
    (
        """
my_array: DynArray[uint256, 5]
@external
def foo(xs: DynArray[uint256, 5]) -> (uint256, DynArray[uint256, 5]):
    for x: uint256 in xs:
        self.my_array.append(x)
    return self.my_array.pop(), self.my_array
    """,
        lambda xs: None if len(xs) == 0 else [xs[-1], xs[:-1]],
    ),
    # test memory arrays
    (
        """
@external
def foo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    ys: DynArray[uint256, 5] = []
    i: uint256 = 0
    for x: uint256 in xs:
        if i >= len(xs) - 1:
            break
        ys.append(x)
        i += 1

    return ys
    """,
        lambda xs: xs[:-1],
    ),
    # check overflow
    (
        """
my_array: DynArray[uint256, 5]
@external
def foo(xs: DynArray[uint256, 6]) -> DynArray[uint256, 5]:
    for x: uint256 in xs:
        self.my_array.append(x)
    return self.my_array
    """,
        lambda xs: None if len(xs) > 5 else xs,
    ),
    # pop to 0 elems
    (
        """
@external
def foo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    ys: DynArray[uint256, 5] = []
    for x: uint256 in xs:
        ys.append(x)
    for x: uint256 in xs:
        ys.pop()
    return ys
    """,
        lambda xs: [],
    ),
    # check underflow
    (
        """
@external
def foo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    ys: DynArray[uint256, 5] = []
    for x: uint256 in xs:
        ys.append(x)
    for x: uint256 in xs:
        ys.pop()
    ys.pop()  # fail
    return ys
    """,
        lambda xs: None,
    ),
    # check underflow
    (
        """
my_array: DynArray[uint256, 5]
@external
def foo(xs: DynArray[uint256, 5]) -> uint256:
    return self.my_array.pop()
    """,
        lambda xs: None,
    ),
]


@pytest.mark.parametrize("subtyp", ["uint8", "int128", "uint256"])
def test_append_literal(get_contract, subtyp):
    data = [1, 2, 3]
    if subtyp == "int128":
        data = [-1, 2, 3]
    code = f"""
@external
def foo() -> DynArray[{subtyp}, 3]:
    x: DynArray[{subtyp}, 3] = []
    x.append({data[0]})
    x.append({data[1]})
    x.append({data[2]})
    return x
    """
    c = get_contract(code)
    assert c.foo() == data


@pytest.mark.parametrize("subtyp,lit", [("uint8", 256), ("uint256", -1), ("int128", 2**127)])
def test_append_invalid_literal(get_contract, assert_compile_failed, subtyp, lit):
    code = f"""
@external
def foo() -> DynArray[{subtyp}, 3]:
    x: DynArray[{subtyp}, 3] = []
    x.append({lit})
    return x
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)


invalid_appends_pops = [
    (
        """
@external
def foo() -> DynArray[uint256, 3]:
    x: DynArray[uint256, 3] = []
    x.append()
    """,
        ArgumentException,
    ),
    (
        """
@external
def foo() -> DynArray[uint256, 3]:
    x: DynArray[uint256, 3] = []
    x.append(1,2)
    """,
        ArgumentException,
    ),
    (
        """
@external
def foo() -> DynArray[uint256, 3]:
    x: DynArray[uint256, 3] = []
    x.pop(1)
    """,
        ArgumentException,
    ),
    (
        """
@external
def foo(x: DynArray[uint256, 3]) -> DynArray[uint256, 3]:
    x.append(1)
    return x
    """,
        ImmutableViolation,
    ),
    (
        """
foo: DynArray[uint256, 3]
@external
@view
def bar() -> DynArray[uint256, 3]:
    self.foo.append(1)
    return self.foo
    """,
        StateAccessViolation,
    ),
]


@pytest.mark.parametrize("code,exception_type", invalid_appends_pops)
def test_invalid_append_pop(get_contract, assert_compile_failed, code, exception_type):
    assert_compile_failed(lambda: get_contract(code), exception_type)


@pytest.mark.parametrize("code,check_result", append_pop_tests)
# TODO change this to fuzz random data
@pytest.mark.parametrize("test_data", [[1, 2, 3, 4, 5][:i] for i in range(6)])
def test_append_pop(get_contract, tx_failed, code, check_result, test_data):
    c = get_contract(code)
    expected_result = check_result(test_data)
    if expected_result is None:
        # None is sentinel to indicate txn should revert
        with tx_failed():
            c.foo(test_data)
    else:
        assert c.foo(test_data) == expected_result


append_pop_complex_tests = [
    (
        """
@external
def foo(x: {typ}) -> DynArray[{typ}, 2]:
    ys: DynArray[{typ}, 1] = []
    ys.append(x)
    return ys
    """,
        lambda x: [x],
    ),
    (
        """
my_array: DynArray[{typ}, 1]
@external
def foo(x: {typ}) -> DynArray[{typ}, 2]:
    self.my_array.append(x)
    self.my_array.append(x)  # fail
    return self.my_array
    """,
        lambda x: None,
    ),
    (
        """
my_array: DynArray[{typ}, 5]
@external
def foo(x: {typ}) -> (DynArray[{typ}, 5], {typ}):
    self.my_array.append(x)
    return self.my_array, self.my_array.pop()
    """,
        lambda x: [[x], x],
    ),
    (
        """
my_array: DynArray[{typ}, 5]
@external
def foo(x: {typ}) -> ({typ}, DynArray[{typ}, 5]):
    self.my_array.append(x)
    return self.my_array.pop(), self.my_array
    """,
        lambda x: [x, []],
    ),
    (
        """
my_array: DynArray[{typ}, 5]
@external
def foo(x: {typ}) -> {typ}:
    return self.my_array.pop()
    """,
        lambda x: None,
    ),
]


@pytest.mark.parametrize("code_template,check_result", append_pop_complex_tests)
@pytest.mark.parametrize(
    "subtype",
    ["uint256[3]", "DynArray[uint256,3]", "DynArray[uint8, 4]", "Foo", "DynArray[Foobar, 3]"],
)
# TODO change this to fuzz random data
def test_append_pop_complex(get_contract, tx_failed, code_template, check_result, subtype):
    code = code_template.format(typ=subtype)
    test_data = [1, 2, 3]
    if subtype == "Foo":
        test_data = tuple(test_data)
        struct_def = """
struct Foo:
    x: uint256
    y: uint256
    z: uint256
        """
        code = struct_def + "\n" + code
    elif subtype == "DynArray[Foobar, 3]":
        flag_def = """
flag Foobar:
    FOO
    BAR
    BAZ
        """
        code = flag_def + "\n" + code
        test_data = [2 ** (i - 1) for i in test_data]

    c = get_contract(code)
    expected_result = check_result(test_data)
    if expected_result is None:
        # None is sentinel to indicate txn should revert
        with tx_failed():
            c.foo(test_data)
    else:
        assert c.foo(test_data) == expected_result


def test_so_many_things_you_should_never_do(get_contract):
    code = """
@internal
def _foo(a: DynArray[uint256, 2], b: DynArray[uint256, 2]) -> DynArray[uint256, 5]:
    return [a[1]-b[0], 2, a[0]-b[1], 8-b[1], 5]

@internal
def _foo2() -> (uint256, uint256):
    b: DynArray[uint256, 2] = [5, 8]
    a: DynArray[uint256, 10] = [6,7,8,9,10,11,12,13,self._foo([44,b[0]],b)[4],16]
    return a[6], 4

@external
def foo() -> (uint256, DynArray[uint256, 3], DynArray[uint256, 2]):
    x: DynArray[uint256, 3] = [
        1,
        14-self._foo2()[0],
        self._foo([7,self._foo2()[0]], [11,self._foo2()[1]])[2]
    ]
    return 666, x, [88, self._foo2()[0]]
    """
    c = get_contract(code)
    assert c.foo() == [666, [1, 2, 3], [88, 12]]


def test_list_of_structs_arg(get_contract):
    code = """
flag Foobar:
    FOO
    BAR

struct Foo:
    x: uint256
    y: uint256
    z: Foobar

@external
def bar(_baz: DynArray[Foo, 3]) -> uint256:
    sum: uint256 = 0
    for i: uint256 in range(3):
        e: Foobar = _baz[i].z
        f: uint256 = convert(e, uint256)
        sum += _baz[i].x * _baz[i].y + f
    return sum
    """
    c = get_contract(code)
    c_input = [[x, y, 1] for x, y in zip(range(3), range(3))]
    assert c.bar(c_input) == 8  # (0 * 0 + 1) + (1 * 1 + 1) + (2 * 2 + 1)


def test_list_of_structs_arg_with_dynamic_type(get_contract):
    code = """
struct Foo:
    x: uint256
    _msg: String[32]

@external
def bar(_baz: DynArray[Foo, 3]) -> String[96]:
    return concat(_baz[0]._msg, _baz[1]._msg, _baz[2]._msg)
    """
    c = get_contract(code)
    c_input = [[i, msg] for i, msg in enumerate(("Hello ", "world", "!!!!"))]
    assert c.bar(c_input) == "Hello world!!!!"


def test_list_of_structs_lists_with_nested_lists(get_contract, tx_failed):
    code = """
struct Bar:
    a: DynArray[uint8[2], 2]

@external
def foo(x: uint8) -> uint8:
    b: DynArray[Bar[2], 2] = [
        [
            Bar(a=[[x, x + 1], [x + 2, x + 3]]),
            Bar(a=[[x + 4, x +5], [x + 6, x + 7]])
        ],
        [
            Bar(a=[[x + 8, x + 9], [x + 10, x + 11]]),
            Bar(a=[[x + 12, x + 13], [x + 14, x + 15]])
        ],
    ]
    return b[0][0].a[0][0] + b[0][1].a[1][1] + b[1][0].a[0][1] + b[1][1].a[1][0]
    """
    c = get_contract(code)
    assert c.foo(17) == 98
    with tx_failed():
        c.foo(241)


def test_list_of_nested_struct_arrays(get_contract):
    code = """
struct Ded:
    a: uint256[3]
    b: bool

struct Foo:
    c: uint256
    d: uint256
    e: Ded

struct Bar:
    f: DynArray[Foo, 3]
    g: DynArray[uint256, 3]

@external
def bar(_bar: DynArray[Bar, 3]) -> uint256:
    sum: uint256 = 0
    for i: uint256 in range(3):
        sum += _bar[i].f[0].e.a[0] * _bar[i].f[1].e.a[1]
    return sum
    """
    c = get_contract(code)
    c_input = [
        ((tuple([(123, 456, ([i, i + 1, i + 2], False))] * 3)), [9, 8, 7]) for i in range(1, 4)
    ]

    assert c.bar(c_input) == 20


def test_2d_list_of_struct(get_contract):
    code = """
struct Bar:
    a: uint256
    b: uint256

@external
def foo(x: DynArray[DynArray[Bar, 2], 2]) -> uint256:
    return x[0][0].a + x[1][1].b
    """
    c = get_contract(code)
    c_input = [([i, i * 2], [i * 3, i * 4]) for i in range(1, 3)]
    assert c.foo(c_input) == 9


def test_3d_list_of_struct(get_contract):
    code = """
struct Bar:
    a: uint256
    b: uint256

@external
def foo(x: DynArray[DynArray[DynArray[Bar, 2], 2], 2]) -> uint256:
    return x[0][0][0].a + x[1][1][1].b
    """
    c = get_contract(code)
    c_input = [([([i, i * 2], [i * 3, i * 4]) for i in range(1, 3)])] * 2
    assert c.foo(c_input) == 9


def test_list_of_static_list(get_contract):
    code = """
@external
def bar(x: int128) -> DynArray[int128[2], 2]:
    a: DynArray[int128[2], 2] = [[x, x * 2], [x * 3, x * 4]]
    return a

@external
def foo(x: int128) -> int128:
    a: DynArray[int128[2], 2] = [[x, x * 2], [x * 3, x * 4]]
    return a[0][0] * a[1][1]
    """
    c = get_contract(code)
    assert c.bar(7) == [[7, 14], [21, 28]]
    assert c.foo(7) == 196


def test_list_of_static_nested_list(get_contract):
    code = """
@external
def bar(x: int128) -> DynArray[int128[2][2], 2]:
    a: DynArray[int128[2][2], 2] = [
        [[x, x * 2], [x * 3, x * 4]],
        [[x * 5, x * 6], [x * 7, x * 8]],
    ]
    return a

@external
def foo(x: int128) -> int128:
    a: DynArray[int128[2][2], 2] = [
        [[x, x * 2], [x * 3, x * 4]],
        [[x * 5, x * 6], [x * 7, x * 8]],
    ]
    return a[0][0][0] * a[1][1][1]
    """
    c = get_contract(code)
    assert c.bar(7) == [[[7, 14], [21, 28]], [[35, 42], [49, 56]]]
    assert c.foo(7) == 392


def test_struct_of_lists(get_contract):
    code = """
struct Foo:
    a1: DynArray[uint256, 2]
    a2: DynArray[DynArray[uint256, 2], 2]
    a3: DynArray[DynArray[DynArray[uint256, 2], 2], 2]

@internal
def _foo() -> DynArray[uint256, 2]:
    return [3, 7]

@internal
def _foo2() -> DynArray[DynArray[uint256, 2], 2]:
    y: DynArray[uint256, 2] = self._foo()
    z: DynArray[uint256, 2] = [y[1], y[0]]
    return [y, z]

@internal
def _foo3() -> DynArray[DynArray[DynArray[uint256, 2], 2], 2]:
    y: DynArray[DynArray[uint256, 2], 2] = self._foo2()
    z: DynArray[DynArray[uint256, 2], 2] = [y[1], y[0]]
    return [y, z]

@external
def bar() -> DynArray[DynArray[DynArray[uint256, 2], 2], 2]:
    foo: Foo = Foo(
        a1=self._foo(),
        a2=self._foo2(),
        a3=self._foo3(),
    )
    return foo.a3
    """
    c = get_contract(code)
    assert c.bar() == [[[3, 7], [7, 3]], [[7, 3], [3, 7]]]


def test_struct_of_lists_2(get_contract):
    code = """
struct Foo:
    b: Bytes[32]
    da: DynArray[int128, 5]
    sa: int128[5]
    some_int: int128

@internal
def _foo(x: int128) -> Foo:
    f: Foo = Foo(
        b=b"hello",
        da=[x, x * 2],
        sa=[x + 1, x + 2, x + 3, x + 4, x + 5],
        some_int=x - 1
    )
    return f

@external
def bar(x: int128) -> DynArray[int128, 5]:
    f: Foo = self._foo(x)
    return f.da
    """
    c = get_contract(code)
    assert c.bar(7) == [7, 14]


def test_struct_of_lists_3(get_contract):
    code = """
struct Foo:
    a: DynArray[int128, 3]
    b: DynArray[address, 3]
    c: DynArray[bool, 3]

@internal
def _foo(x: int128) -> Foo:
    f: Foo = Foo(
        a=[x, x * 2],
        b=[0x0000000000000000000000000000000000000012],
        c=[False, True, False]
    )
    return f

@external
def bar(x: int128) -> DynArray[int128, 3]:
    f: Foo = self._foo(x)
    return f.a
    """
    c = get_contract(code)
    assert c.bar(7) == [7, 14]


def test_nested_struct_of_lists(get_contract, assert_compile_failed, optimize):
    code = """
struct nestedFoo:
    a1: DynArray[DynArray[DynArray[uint256, 2], 2], 2]

struct Foo:
    b1: DynArray[DynArray[DynArray[nestedFoo, 2], 2], 2]

@internal
def _foo() -> nestedFoo:
    return nestedFoo(a1=[
        [[3, 7], [7, 3]],
        [[7, 3], [3, 7]],
    ])

@internal
def _foo2() -> Foo:
    _nF1: nestedFoo = self._foo()
    return Foo(b1=[[[_nF1, _nF1], [_nF1, _nF1]], [[_nF1, _nF1], [_nF1, _nF1]]])

@internal
def _foo3(f: Foo) -> Foo:
    new_f: Foo = f
    new_f.b1[0][1][0].a1[0][0] = [0, 0]
    new_f.b1[1][0][0].a1[0][1] = [0, 0]
    new_f.b1[1][1][0].a1[1][1] = [0, 0]
    return new_f

@external
def bar() -> DynArray[DynArray[DynArray[uint256, 2], 2], 2]:
    foo: Foo = self._foo2()
    return self._foo3(foo).b1[1][1][0].a1

@external
def bar2() -> uint256:
    foo: Foo = self._foo2()
    newFoo: Foo = self._foo3(foo)
    return newFoo.b1[1][1][0].a1[1][1][0] + \\
        newFoo.b1[1][0][0].a1[0][1][1] + \\
        newFoo.b1[0][1][0].a1[0][0][0]
    """
    c = get_contract(code)
    assert c.bar() == [[[3, 7], [7, 3]], [[7, 3], [0, 0]]]
    assert c.bar2() == 0


def test_tuple_of_lists(get_contract):
    code = """
@internal
def _foo() -> DynArray[uint256, 2]:
    return [3, 7]

@internal
def _foo2() -> DynArray[DynArray[uint256, 2], 2]:
    y: DynArray[uint256, 2] = self._foo()
    z: DynArray[uint256, 2] = [y[1], y[0]]
    return [y, z]

@internal
def _foo3() -> DynArray[DynArray[DynArray[uint256, 2], 2], 2]:
    y: DynArray[DynArray[uint256, 2], 2] = self._foo2()
    z: DynArray[DynArray[uint256, 2], 2] = [y[1], y[0]]
    return [y, z]

@internal
def _foo4() -> (DynArray[DynArray[uint256, 2], 2], DynArray[DynArray[DynArray[uint256, 2], 2], 2]):
    return (self._foo2(), self._foo3())

@external
def bar() -> uint256:
    a: DynArray[DynArray[uint256, 2], 2] = [[0, 0], [0, 0]]
    b: DynArray[DynArray[DynArray[uint256, 2], 2], 2] = [[[0, 0], [0, 0]], [[0, 0], [0, 0]]]
    a, b = self._foo4()
    return a[0][0] * b[1][0][1] + a[1][0] * b[0][1][0]
    """
    c = get_contract(code)
    assert c.bar() == 58


def test_constant_list(get_contract, tx_failed):
    some_good_primes = [5.0, 11.0, 17.0, 29.0, 37.0, 41.0]
    code = f"""
MY_LIST: constant(DynArray[decimal, 6]) = {some_good_primes}
@external
def ix(i: uint256) -> decimal:
    return MY_LIST[i]
    """
    c = get_contract(code)
    for i, p in enumerate(some_good_primes):
        assert c.ix(i) == p
    # assert oob
    with tx_failed():
        c.ix(len(some_good_primes) + 1)


def test_public_dynarray(get_contract):
    code = """
my_list: public(DynArray[uint256, 5])
@deploy
def __init__():
    self.my_list = [1,2,3]
    """
    c = get_contract(code)

    for i, t in enumerate([1, 2, 3]):
        assert c.my_list(i) == t


def test_nested_public_dynarray(get_contract):
    code = """
my_list: public(DynArray[DynArray[uint256, 5], 5])
@deploy
def __init__():
    self.my_list = [[1,2,3]]
    """
    c = get_contract(code)

    for i, l in enumerate([[1, 2, 3]]):
        for j, t in enumerate(l):
            assert c.my_list(i, j) == t


@pytest.mark.parametrize(
    "typ,val",
    [
        ("DynArray[DynArray[uint256, 5], 5]", [[], []]),
        ("DynArray[DynArray[DynArray[uint256, 5], 5], 5]", [[[], []], []]),
    ],
)
def test_empty_nested_dynarray(get_contract, typ, val):
    code = f"""
@external
def foo() -> {typ}:
    a: {typ} = {val}
    return a
    """
    c = get_contract(code)
    assert c.foo() == val


# TODO test negative public(DynArray) cases?


# CMC 2022-08-04 these are blocked due to typechecker bug; leaving as
# negative tests so we know if/when the typechecker is fixed.
# (don't consider it a high priority to fix since membership in
# in empty list literal seems like something we should plausibly
# reject at compile-time anyway)
def test_empty_list_membership_fail(get_contract, assert_compile_failed):
    code = """
@external
def foo(x: uint256) -> bool:
    return x in []
    """
    assert_compile_failed(lambda: get_contract(code))
    code = """
@external
def foo(x: uint256) -> bool:
    return x not in []
    """
    assert_compile_failed(lambda: get_contract(code))


# Would be nice to put this somewhere accessible, like in vyper.types or something
integer_types = ["uint8", "int128", "int256", "uint256"]


@pytest.mark.parametrize("storage_type,return_type", itertools.permutations(integer_types, 2))
def test_constant_list_fail(get_contract, assert_compile_failed, storage_type, return_type):
    code = f"""
MY_CONSTANT: constant(DynArray[{storage_type}, 3]) = [1, 2, 3]

@external
def foo() -> DynArray[{return_type}, 3]:
    return MY_CONSTANT
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)


@pytest.mark.parametrize("storage_type,return_type", itertools.permutations(integer_types, 2))
def test_constant_list_fail_2(get_contract, assert_compile_failed, storage_type, return_type):
    code = f"""
MY_CONSTANT: constant(DynArray[{storage_type}, 3]) = [1, 2, 3]

@external
def foo() -> {return_type}:
    return MY_CONSTANT[0]
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)


@pytest.mark.parametrize("storage_type,return_type", itertools.permutations(integer_types, 2))
def test_constant_list_fail_3(get_contract, assert_compile_failed, storage_type, return_type):
    code = f"""
MY_CONSTANT: constant(DynArray[{storage_type}, 3]) = [1, 2, 3]

@external
def foo(i: uint256) -> {return_type}:
    return MY_CONSTANT[i]
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)


dynarray_length_no_clobber_cases = [
    # GHSA-3p37-3636-q8wv cases
    """
a: DynArray[uint256,3]

@external
def should_revert() -> DynArray[uint256,3]:
    self.a = [1,2,3]
    self.a = empty(DynArray[uint256,3])
    self.a = [self.a[0], self.a[1], self.a[2]]

    return self.a  # if bug: returns [1,2,3]
    """,
    """
@external
def should_revert() -> DynArray[uint256,3]:
    self.a()
    return self.b() # if bug: returns [1,2,3]

@internal
def a():
    a: uint256 = 0
    b: uint256 = 1
    c: uint256 = 2
    d: uint256 = 3

@internal
def b() -> DynArray[uint256,3]:
    a: DynArray[uint256,3] = empty(DynArray[uint256,3])
    a = [a[0],a[1],a[2]]
    return a
    """,
    """
a: DynArray[uint256,4]

@external
def should_revert() -> DynArray[uint256,4]:
    self.a = [1,2,3]
    self.a = empty(DynArray[uint256,4])
    self.a = [4, self.a[0]]

    return self.a  # if bug: return [4, 4]
    """,
    """
@external
def should_revert() -> DynArray[uint256,4]:
    a: DynArray[uint256, 4] = [1,2,3]
    a = []

    a = [a.pop()]  # if bug: return [1]

    return a
    """,
    """
@external
def should_revert():
    c: DynArray[uint256, 1] = []
    c.append(c[0])
    """,
    """
@external
def should_revert():
    c: DynArray[uint256, 1] = [1]
    c[0] = c.pop()
    """,
    """
@external
def should_revert():
    c: DynArray[DynArray[uint256, 1], 2] = [[]]
    c[0] = c.pop()
    """,
    """
a: DynArray[String[65],2]

@external
def should_revert() -> DynArray[String[65], 2]:
    self.a = ["hello", "world"]
    self.a = []
    self.a = [self.a[0], self.a[1]]

    return self.a  # if bug: return ["hello", "world"]
    """,
]


@pytest.mark.parametrize("code", dynarray_length_no_clobber_cases)
def test_dynarray_length_no_clobber(get_contract, tx_failed, code):
    # check that length is not clobbered before dynarray data copy happens
    c = get_contract(code)
    with tx_failed():
        c.should_revert()
