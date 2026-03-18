import pytest

from vyper.exceptions import (
    ArrayIndexException,
    InvalidOperation,
    InvalidReference,
    TypeMismatch,
    UndeclaredDefinition,
    UnknownAttribute,
)
from vyper.semantics.analysis.base import VarInfo
from vyper.semantics.analysis.utils import get_possible_types_from_node
from vyper.semantics.types import AddressT, BoolT, DArrayT, SArrayT
from vyper.semantics.types.shortcuts import INT128_T

INTEGER_LITERALS = [(42, 31337), (-1, 1), (69, 2**128)]
DECIMAL_LITERALS = [("4.2", "-1.337")]
BOOL_LITERALS = [(True, False), (True, True), (False, False)]
STRING_LITERALS = [("'hi'", "'there'"), ("'foo'", "'bar'"), ("'longer'", "'short'")]


def test_attribute(build_node, namespace):
    node = build_node("self.foo")
    with namespace.enter_scope():
        namespace["self"].typ.add_member("foo", INT128_T)
        assert get_possible_types_from_node(node) == [INT128_T]


def test_attribute_missing_self(build_node, namespace):
    node = build_node("foo")
    with namespace.enter_scope():
        namespace["self"].typ.add_member("foo", INT128_T)
        with pytest.raises(InvalidReference):
            get_possible_types_from_node(node)


def test_attribute_not_in_self(build_node, namespace):
    node = build_node("self.foo")
    with namespace.enter_scope():
        namespace["foo"] = INT128_T
        with pytest.raises(InvalidReference):
            get_possible_types_from_node(node)


def test_attribute_unknown(build_node, namespace):
    node = build_node("foo.bar")
    with namespace.enter_scope():
        namespace["foo"] = AddressT()
        with pytest.raises(UnknownAttribute):
            get_possible_types_from_node(node)


def test_attribute_not_member_type(build_node, namespace):
    node = build_node("foo.bar")
    with namespace.enter_scope():
        namespace["foo"] = INT128_T
        with pytest.raises(UnknownAttribute):
            get_possible_types_from_node(node)


@pytest.mark.parametrize("op", ["+", "-", "*", "//", "%"])
@pytest.mark.parametrize("left,right", INTEGER_LITERALS)
def test_binop_ints(build_node, namespace, op, left, right):
    node = build_node(f"{left}{op}{right}")
    with namespace.enter_scope():
        get_possible_types_from_node(node)


@pytest.mark.parametrize("op", "+-*/%")
@pytest.mark.parametrize("left,right", DECIMAL_LITERALS)
def test_binop_decimal(build_node, namespace, op, left, right):
    node = build_node(f"{left}{op}{right}")
    with namespace.enter_scope():
        get_possible_types_from_node(node)


@pytest.mark.parametrize("op", "+-*/%")
@pytest.mark.parametrize("left,right", [(42, "2.3"), (-1, 2**255)])
def test_binop_type_mismatch(build_node, namespace, op, left, right):
    node = build_node(f"{left}{op}{right}")
    with namespace.enter_scope():
        with pytest.raises(TypeMismatch):
            get_possible_types_from_node(node)


def test_binop_invalid_decimal_pow(build_node, namespace):
    node = build_node("2.1 ** 2.1")
    with namespace.enter_scope():
        with pytest.raises(InvalidOperation):
            get_possible_types_from_node(node)


@pytest.mark.parametrize("left, right", STRING_LITERALS + BOOL_LITERALS)
@pytest.mark.parametrize("op", "+-*/%")
def test_binop_invalid_op(build_node, namespace, op, left, right):
    node = build_node(f"{left} {op} {right}")
    with namespace.enter_scope():
        with pytest.raises(InvalidOperation):
            get_possible_types_from_node(node)


@pytest.mark.parametrize("left, right", BOOL_LITERALS)
@pytest.mark.parametrize("op", ["and", "or"])
def test_boolop(build_node, namespace, op, left, right):
    node = build_node(f"{left} {op} {right}")
    with namespace.enter_scope():
        types_list = get_possible_types_from_node(node)

    assert types_list == [BoolT()]


@pytest.mark.parametrize("left, right", INTEGER_LITERALS + DECIMAL_LITERALS + STRING_LITERALS)
@pytest.mark.parametrize("op", ["and", "or"])
def test_boolop_invalid_op(build_node, namespace, op, left, right):
    node = build_node(f"{left} {op} {right}")
    with namespace.enter_scope():
        with pytest.raises(InvalidOperation):
            get_possible_types_from_node(node)


@pytest.mark.parametrize("left, right", INTEGER_LITERALS + DECIMAL_LITERALS)
@pytest.mark.parametrize("op", ["<", "<=", ">", ">="])
def test_compare_lt_gt(build_node, namespace, op, left, right):
    node = build_node(f"{left} {op} {right}")
    with namespace.enter_scope():
        types_list = get_possible_types_from_node(node)

    assert types_list == [BoolT()]


@pytest.mark.parametrize(
    "left, right", INTEGER_LITERALS + DECIMAL_LITERALS + BOOL_LITERALS + STRING_LITERALS
)
@pytest.mark.parametrize("op", ["==", "!="])
def test_compare_eq_ne(build_node, namespace, op, left, right):
    node = build_node(f"{left} {op} {right}")
    with namespace.enter_scope():
        types_list = get_possible_types_from_node(node)

    assert types_list == [BoolT()]


@pytest.mark.parametrize("left, right", BOOL_LITERALS + STRING_LITERALS)
@pytest.mark.parametrize("op", ["<", "<=", ">", ">="])
def test_compare_invalid_op(build_node, namespace, op, left, right):
    node = build_node(f"{left} {op} {right}")
    with namespace.enter_scope():
        with pytest.raises(InvalidOperation):
            get_possible_types_from_node(node)


def test_name(build_node, namespace):
    node = build_node("foo")
    type_def = INT128_T
    namespace["foo"] = VarInfo(type_def)

    assert get_possible_types_from_node(node) == [type_def]


def test_name_unknown(build_node, namespace):
    node = build_node("foo")
    with pytest.raises(UndeclaredDefinition):
        get_possible_types_from_node(node)


@pytest.mark.parametrize("left, right", INTEGER_LITERALS + DECIMAL_LITERALS + BOOL_LITERALS)
def test_list(build_node, namespace, left, right):
    node = build_node(f"[{left}, {right}]")

    with namespace.enter_scope():
        types_list = get_possible_types_from_node(node)

    assert types_list
    for item in types_list:
        assert isinstance(item, (DArrayT, SArrayT))


def test_subscript(build_node, namespace):
    node = build_node("foo[1]")
    type_ = INT128_T

    namespace["foo"] = VarInfo(SArrayT(type_, 3))
    assert get_possible_types_from_node(node) == [type_]


def test_subscript_out_of_bounds(build_node, namespace):
    node = build_node("foo[5]")
    type_def = INT128_T

    namespace["foo"] = VarInfo(SArrayT(type_def, 3))
    with pytest.raises(ArrayIndexException):
        get_possible_types_from_node(node)


def test_subscript_negative(build_node, namespace):
    node = build_node("foo[-1]")
    type_def = INT128_T

    namespace["foo"] = VarInfo(SArrayT(type_def, 3))
    with pytest.raises(ArrayIndexException):
        get_possible_types_from_node(node)


def test_tuple(build_node, namespace):
    node = build_node("(foo, bar)")

    namespace["foo"] = VarInfo(INT128_T)
    namespace["bar"] = VarInfo(AddressT())
    types_list = get_possible_types_from_node(node)

    assert types_list[0].member_types == [namespace["foo"].typ, namespace["bar"].typ]


def test_tuple_subscript(build_node, namespace):
    node = build_node("(foo, bar)[1]")

    namespace["foo"] = VarInfo(INT128_T)
    namespace["bar"] = VarInfo(AddressT())
    types_list = get_possible_types_from_node(node)

    assert types_list == [namespace["bar"].typ]
