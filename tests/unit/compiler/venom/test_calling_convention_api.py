from vyper.codegen_venom.calling_convention import is_word_type, pass_via_stack, returns_stack_count
from vyper.semantics.analysis.base import FunctionVisibility, StateMutability
from vyper.semantics.types import AddressT, BoolT
from vyper.semantics.types.function import ContractFunctionT, PositionalArg
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.semantics.types.subscriptable import SArrayT, TupleT


def _make_func(args, return_type=None):
    pos_args = [PositionalArg(name=name, typ=typ) for name, typ in args]
    return ContractFunctionT(
        name="test_fn",
        positional_args=pos_args,
        keyword_args=[],
        return_type=return_type,
        function_visibility=FunctionVisibility.INTERNAL,
        state_mutability=StateMutability.NONPAYABLE,
    )


# -- is_word_type --


def test_is_word_type_uint256():
    assert is_word_type(UINT256_T) is True


def test_is_word_type_bool():
    assert is_word_type(BoolT()) is True


def test_is_word_type_address():
    assert is_word_type(AddressT()) is True


def test_is_word_type_sarray_one_element():
    # uint256[1] is 32 bytes but NOT a primitive word
    assert is_word_type(SArrayT(UINT256_T, 1)) is False


def test_is_word_type_sarray_two_elements():
    assert is_word_type(SArrayT(UINT256_T, 2)) is False


# -- returns_stack_count --


def test_returns_stack_count_none():
    func_t = _make_func([])
    assert returns_stack_count(func_t) == 0


def test_returns_stack_count_single_word():
    func_t = _make_func([], return_type=UINT256_T)
    assert returns_stack_count(func_t) == 1


def test_returns_stack_count_single_non_word():
    func_t = _make_func([], return_type=SArrayT(UINT256_T, 1))
    assert returns_stack_count(func_t) == 0


def test_returns_stack_count_tuple_two_words():
    func_t = _make_func([], return_type=TupleT([UINT256_T, UINT256_T]))
    assert returns_stack_count(func_t) == 2


def test_returns_stack_count_tuple_three_words():
    # exceeds MAX_STACK_RETURNS (2)
    func_t = _make_func([], return_type=TupleT([UINT256_T, UINT256_T, UINT256_T]))
    assert returns_stack_count(func_t) == 0


def test_returns_stack_count_tuple_mixed():
    func_t = _make_func([], return_type=TupleT([UINT256_T, SArrayT(UINT256_T, 1)]))
    assert returns_stack_count(func_t) == 0


# -- pass_via_stack --


def test_pass_via_stack_six_word_args():
    args = [(f"a{i}", UINT256_T) for i in range(6)]
    func_t = _make_func(args)
    result = pass_via_stack(func_t)
    assert all(result.values())


def test_pass_via_stack_seven_word_args():
    args = [(f"a{i}", UINT256_T) for i in range(7)]
    func_t = _make_func(args)
    result = pass_via_stack(func_t)
    assert result["a6"] is False
    assert sum(v for v in result.values()) == 6


def test_pass_via_stack_with_single_return():
    # 1 return slot + 5 args = 6 total
    args = [(f"a{i}", UINT256_T) for i in range(6)]
    func_t = _make_func(args, return_type=UINT256_T)
    result = pass_via_stack(func_t)
    assert result["a4"] is True
    assert result["a5"] is False


def test_pass_via_stack_with_tuple_return():
    # 2 return slots + 4 args = 6 total
    args = [(f"a{i}", UINT256_T) for i in range(6)]
    func_t = _make_func(args, return_type=TupleT([UINT256_T, UINT256_T]))
    result = pass_via_stack(func_t)
    assert result["a3"] is True
    assert result["a4"] is False
    assert result["a5"] is False


def test_pass_via_stack_non_word_arg():
    args = [("arr", SArrayT(UINT256_T, 1)), ("x", UINT256_T)]
    func_t = _make_func(args)
    result = pass_via_stack(func_t)
    assert result["arr"] is False
    assert result["x"] is True
