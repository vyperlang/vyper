import pytest

import vyper
from tests.venom_utils import PrePostChecker
from vyper.venom.passes import (
    AffineFoldingPass,
    AlgebraicOptimizationPass,
    RemoveUnusedVariablesPass,
)

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker(
    [AffineFoldingPass, AlgebraicOptimizationPass, RemoveUnusedVariablesPass]
)


@pytest.mark.parametrize("iszero_count", range(5))
def test_simple_jump_case(iszero_count):
    """
    Test remove iszero chains to jnz
    """

    iszero_chain = ""
    for i in range(iszero_count):
        new = i + 1
        iszero_chain += f"""
        %cond{new} = iszero %cond{i}"""
    iszero_chain_output = f"cond{iszero_count}"

    pre = f"""
    main:
        %par = source
        %1 = %par
        %2 = 64
        %3 = add %1, %2
        %cond0 = %3
        {iszero_chain}
        jnz %{iszero_chain_output}, @then, @else
    then:
        %4 = add 10, %3
        sink %4
    else:
        %5 = add %3, %par
        sink %5
    """

    if iszero_count % 2 == 1:
        post_chain = "%cond1 = iszero %cond0"
        jnz_cond = "cond1"
    else:
        post_chain = ""
        jnz_cond = "cond0"

    post = f"""
    main:
        %par = source
        %1 = %par
        %2 = 64
        %3 = add %1, %2
        %cond0 = %3
        {post_chain}
        jnz %{jnz_cond}, @then, @else
    then:
        %4 = add 10, %3
        sink %4
    else:
        %5 = add %3, %par
        sink %5
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("iszero_count", range(1, 5))
def test_simple_bool_cast_case(iszero_count):
    """
    Test that iszero chain elimination would not eliminate
    bool cast

    sink(izero(iszero(iszero(iszero(x))))) => sink(iszero(iszero(x)))

    You cannot remove all iszeros because the sink expects the bool
    and the total elimination would invalidate it
    """

    iszero_chain = ""
    for i in range(iszero_count):
        new = i + 1
        iszero_chain += f"""
        %cond{new} = iszero %cond{i}"""

    iszero_chain_output = f"cond{iszero_count}"

    pre = f"""
    main:
        %par = source
        %1 = %par
        %2 = 64
        %3 = add %1, %2
        %cond0 = %3
        {iszero_chain}
        sink %{iszero_chain_output}
    """

    if iszero_count % 2 == 0:
        post_chain = """
        %cond1 = iszero %cond0
        %cond2 = iszero %cond1
        """
        end_cond = "cond2"
    else:
        post_chain = """
        %cond1 = iszero %cond0
        """
        end_cond = "cond1"

    post = f"""
    main:
        %par = source
        %1 = %par
        %2 = 64
        %3 = add %1, %2
        %cond0 = %3
        {post_chain}
        sink %{end_cond}
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("interleave_point", range(5))
def test_interleaved_case(interleave_point):
    """
    Test for the case where one of the iszeros results in
    the chain is used by another instruction (outside the chain)
    """

    iszeros_after_interleave_point = interleave_point // 2

    total_iszeros = interleave_point + iszeros_after_interleave_point

    iszero_chain = ""
    for i in range(interleave_point):
        new = i + 2
        iszero_chain += f"""
        %cond{new} = iszero %cond{i + 1}"""

    # use a variable from middle of iszero chain.
    # (note we start the chain from cond1)
    mstore_cond = interleave_point + 1

    # continue building on iszero_chain1
    continue_iszero_chain = ""
    for i0 in range(iszeros_after_interleave_point):
        i = i0 + interleave_point + 1
        new = i + 1
        continue_iszero_chain += f"""
        %cond{new} = iszero %cond{i}"""

    # output of iszero chain
    jnz_cond = total_iszeros + 1

    pre = f"""
    main:
        %par = source
        %cond0 = add 64, %par
        %cond1 = iszero %cond0
        {iszero_chain}
        mstore %par, %cond{mstore_cond}
        {continue_iszero_chain}
        jnz %cond{jnz_cond}, @then, @else
    then:
        %2 = add 10, %par

        ; mload to sink value for hevm
        %4 = mload %par
        sink %2, %4
    else:
        %3 = add %cond0, %par
        %5 = mload %par
        sink %3, %5
    """

    post_iszero = "%cond2 = iszero %cond1" if interleave_point % 2 == 1 else ""

    mstore_cond = (interleave_point % 2) + 1
    jnz_cond = (total_iszeros + 1) % 2

    post = f"""
    main:
        %par = source
        %cond0 = add 64, %par
        %cond1 = iszero %cond0
        {post_iszero}
        mstore %par, %cond{mstore_cond}
        jnz %cond{jnz_cond}, @then, @else
    then:
        %2 = add 10, %par
        %4 = mload %par
        sink %2, %4
    else:
        %3 = add %cond0, %par
        %5 = mload %par
        sink %3, %5
    """

    _check_pre_post(pre, post)


def test_fold_add_chain():
    """add(add(x, 3), 5) => add(x, 8)"""
    pre = """
    main:
        %x = source
        %tmp = add 3, %x
        %out = add 5, %tmp
        sink %out
    """
    post = """
    main:
        %x = source
        %out = add 8, %x
        sink %out
    """
    _check_pre_post(pre, post)


def test_fold_sub_lit_chain():
    """(x + 10) - 3 => x + 7 (sub with var - lit)"""
    pre = """
    main:
        %x = source
        %tmp = add 10, %x
        %out = sub %tmp, 3
        sink %out
    """
    post = """
    main:
        %x = source
        %out = add 7, %x
        sink %out
    """
    _check_pre_post(pre, post)


def test_fold_add_chain_cancels_to_zero():
    """(x + 5) - 5 => x (constants cancel)"""
    pre = """
    main:
        %x = source
        %tmp = add 5, %x
        %out = sub %tmp, 5
        sink %out
    """
    post = """
    main:
        %x = source
        %out = assign %x
        sink %out
    """
    _check_pre_post(pre, post)


def test_fold_add_chain_multi_use_stops():
    """Don't fold through intermediates with multiple uses."""
    pre = """
    main:
        %x = source
        %tmp = add 3, %x
        %out = add 5, %tmp
        sink %out, %tmp
    """
    post = """
    main:
        %x = source
        %tmp = add 3, %x
        %out = add 5, %tmp
        sink %out, %tmp
    """
    _check_pre_post(pre, post)


def test_fold_stops_at_multi_use_intermediate():
    """Don't fold past a multi-use intermediate deeper in the chain.
    %a has multiple uses so it should be preserved as the base, even
    though the lattice flattens all the way to %x."""
    pre = """
    main:
        %x = source
        %a = add 3, %x
        %b = add 5, %a
        %out = add 7, %b
        sink %out, %a
    """
    # %a is multi-use (sink + %b). %b is single-use.
    # The walk stops at %a: %out = %a + 12, not %x + 15.
    post = """
    main:
        %x = source
        %a = add 3, %x
        %out = add 12, %a
        sink %out, %a
    """
    _check_pre_post(pre, post)


def test_fold_add_chain_three_deep():
    """add(add(add(x, 1), 2), 3) => add(x, 6)"""
    pre = """
    main:
        %x = source
        %t1 = add 1, %x
        %t2 = add 2, %t1
        %out = add 3, %t2
        sink %out
    """
    post = """
    main:
        %x = source
        %out = add 6, %x
        sink %out
    """
    _check_pre_post(pre, post)


def test_iszero_chain_after_comparator_rewrite():
    """Comparator rewrite can mutate an iszero in the chain (e.g. gt -> slt
    removes an iszero), making the pre-computed iszero_depth stale.
    The walk must bail out gracefully instead of asserting."""
    pre = """
    main:
        %x = source
        %cmp = gt %x, 5
        %a = iszero %cmp
        %b = iszero %a
        jnz %b, @then, @else
    then:
        sink %x
    else:
        sink %x
    """
    # The comparator handler flips gt to lt and absorbs the iszero
    # at %a (converting it to assign). The chain is now stale —
    # %cmp has inverted semantics. The chain validator detects that
    # %a is no longer iszero and bails out, leaving jnz %b intact.
    post = """
    main:
        %x = source
        %cmp = gt 6, %x
        %a = %cmp
        %b = iszero %a
        jnz %b, @then, @else
    then:
        sink %x
    else:
        sink %x
    """
    _check_pre_post(pre, post)


def test_offsets():
    """
    Test of addition to offset rewrites
    """

    pre = """
    main:
        %par = source
        %1 = add @main, 0
        %2 = add 0, @main
        %3 = add %par, @main
        sink %1, %2, %3
    """

    post = """
    main:
        %par = source
        %1 = offset @main, 0

        ; TODO fix this, should be `offset @main, 0`
        ; (also, the `assign` opcode is used directly because
        ; the parser does not see the label as literal)
        %2 = assign @main
        %3 = add %par, @main
        sink %1, %2, %3
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("iszero_count", range(5))
def test_assert_unreachable_iszero_chain(iszero_count):
    """
    Test that iszero chains are optimized for assert_unreachable
    the same way they are for jnz (truthy context)
    """
    iszero_chain = ""
    for i in range(iszero_count):
        new = i + 1
        iszero_chain += f"""
        %cond{new} = iszero %cond{i}"""
    iszero_chain_output = f"cond{iszero_count}"

    pre = f"""
    main:
        %par = source
        %cond0 = add %par, 64
        {iszero_chain}
        assert_unreachable %{iszero_chain_output}
        sink %par
    """

    if iszero_count % 2 == 1:
        post_chain = "%cond1 = iszero %cond0"
        assert_cond = "cond1"
    else:
        post_chain = ""
        assert_cond = "cond0"

    # note: add operands flipped due to commutative normalization
    post = f"""
    main:
        %par = source
        %cond0 = add 64, %par
        {post_chain}
        assert_unreachable %{assert_cond}
        sink %par
    """

    _check_pre_post(pre, post)


# Test the case of https://github.com/vyperlang/vyper/issues/4288
def test_ssa_after_algebraic_optimization():
    code = """
@internal
def _do_math(x: uint256) -> uint256:
    value: uint256 = x
    result: uint256 = 0

    if (x >> 128 != 0):
        x >>= 128
    if (x >> 64 != 0):
        x >>= 64

    if 1 < value:
        result = 1

    return result

@external
def run() -> uint256:
    return self._do_math(10)
    """

    vyper.compile_code(code, output_formats=["bytecode"])
