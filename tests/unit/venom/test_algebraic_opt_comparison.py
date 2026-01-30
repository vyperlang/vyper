"""
Tests for var-vs-var comparison folding in AlgebraicOptimizationPass.

Tests cover:
- Basic unsigned comparisons (lt, gt) with non-overlapping ranges
- Basic signed comparisons (slt, sgt) with non-overlapping ranges
- Sign boundary edge cases (ranges spanning negative/non-negative)
- Overlapping ranges (should NOT fold)
- Boundary touching cases
"""

from tests.venom_utils import PrePostChecker
from vyper.venom.passes.algebraic_optimization import AlgebraicOptimizationPass
from vyper.venom.passes.assert_elimination import AssertEliminationPass
from vyper.venom.passes.remove_unused_variables import RemoveUnusedVariablesPass

_check_pre_post = PrePostChecker([AlgebraicOptimizationPass, RemoveUnusedVariablesPass])
_check_with_assert_elim = PrePostChecker(
    [AlgebraicOptimizationPass, AssertEliminationPass, RemoveUnusedVariablesPass]
)


# =============================================================================
# UNSIGNED LT: Non-overlapping ranges
# =============================================================================


def test_lt_var_var_disjoint_always_true():
    """
    lt a, b where a.hi < b.lo → always true (1)
    a ∈ [0, 99], b ∈ [100, 200] → a < b always
    """
    pre = """
    main:
        %x = source
        %y = source
        %a = and %x, 99
        %b_base = and %y, 100
        %b = add %b_base, 100
        %cmp = lt %a, %b
        sink %cmp
    """

    # After folding, %cmp = 1, and unused vars are removed
    post = """
    main:
        %cmp = 1
        sink %cmp
    """

    _check_pre_post(pre, post)


def test_lt_var_var_disjoint_always_false():
    """
    lt a, b where a.lo >= b.hi → always false (0)
    a ∈ [100, 200], b ∈ [0, 99] → a < b never
    """
    pre = """
    main:
        %x = source
        %y = source
        %a_base = and %x, 100
        %a = add %a_base, 100
        %b = and %y, 99
        %cmp = lt %a, %b
        sink %cmp
    """

    post = """
    main:
        %cmp = 0
        sink %cmp
    """

    _check_pre_post(pre, post)


# =============================================================================
# UNSIGNED GT: Non-overlapping ranges
# =============================================================================


def test_gt_var_var_disjoint_always_true():
    """
    gt a, b where a.lo > b.hi → always true (1)
    a ∈ [100, 200], b ∈ [0, 99] → a > b always
    """
    pre = """
    main:
        %x = source
        %y = source
        %a_base = and %x, 100
        %a = add %a_base, 100
        %b = and %y, 99
        %cmp = gt %a, %b
        sink %cmp
    """

    post = """
    main:
        %cmp = 1
        sink %cmp
    """

    _check_pre_post(pre, post)


def test_gt_var_var_disjoint_always_false():
    """
    gt a, b where a.hi <= b.lo → always false (0)
    a ∈ [0, 99], b ∈ [100, 200] → a > b never
    """
    pre = """
    main:
        %x = source
        %y = source
        %a = and %x, 99
        %b_base = and %y, 100
        %b = add %b_base, 100
        %cmp = gt %a, %b
        sink %cmp
    """

    post = """
    main:
        %cmp = 0
        sink %cmp
    """

    _check_pre_post(pre, post)


# =============================================================================
# OVERLAPPING RANGES: Should NOT fold
# =============================================================================


def test_lt_var_var_overlapping_no_fold():
    """
    lt a, b where ranges overlap → cannot fold
    a ∈ [0, 255], b ∈ [100, 200] → overlap at [100, 200]
    """
    pre = """
    main:
        %x = source
        %y = source
        %a = and %x, 255
        %b_base = and %y, 100
        %b = add %b_base, 100
        %cmp = lt %a, %b
        sink %cmp
    """

    # Should remain unchanged (comparison not folded)
    # Note: operands get canonicalized (literal first for commutative ops)
    post = """
    main:
        %x = source
        %y = source
        %a = and 255, %x
        %b_base = and 100, %y
        %b = add 100, %b_base
        %cmp = lt %a, %b
        sink %cmp
    """

    _check_pre_post(pre, post)


def test_gt_var_var_unknown_range_no_fold():
    """
    gt a, b where one operand has unknown range → cannot fold
    """
    pre = """
    main:
        %a = source
        %y = source
        %b = and %y, 99
        %cmp = gt %a, %b
        sink %cmp
    """

    # Should remain unchanged - %a has TOP range
    # Note: operands get canonicalized
    post = """
    main:
        %a = source
        %y = source
        %b = and 99, %y
        %cmp = gt %a, %b
        sink %cmp
    """

    _check_pre_post(pre, post)


# =============================================================================
# BOUNDARY TOUCHING CASES
# =============================================================================


def test_lt_boundary_touching_false():
    """
    lt a, b where a.lo == b.hi → always false
    a ∈ [100, 200], b ∈ [0, 100] → a >= 100, b <= 100, so a >= b
    """
    pre = """
    main:
        %x = source
        %y = source
        %a_base = and %x, 100
        %a = add %a_base, 100
        %b = and %y, 100
        %cmp = lt %a, %b
        sink %cmp
    """

    post = """
    main:
        %cmp = 0
        sink %cmp
    """

    _check_pre_post(pre, post)


def test_gt_boundary_touching_false():
    """
    gt a, b where a.hi == b.lo → always false
    a ∈ [0, 100], b ∈ [100, 200] → a <= 100, b >= 100, so a <= b
    """
    pre = """
    main:
        %x = source
        %y = source
        %a = and %x, 100
        %b_base = and %y, 100
        %b = add %b_base, 100
        %cmp = gt %a, %b
        sink %cmp
    """

    post = """
    main:
        %cmp = 0
        sink %cmp
    """

    _check_pre_post(pre, post)


# =============================================================================
# MODULO RESULTS (common pattern)
# =============================================================================


def test_lt_modulo_result_always_bounded():
    """
    After modulo, result is always less than the divisor.
    a = x % 100 → a ∈ [0, 99]
    b = y % 1000 + 100 → b ∈ [100, 1099]
    lt a, b → always true
    """
    pre = """
    main:
        %x = source
        %y = source
        %a = mod %x, 100
        %b_mod = mod %y, 1000
        %b = add %b_mod, 100
        %cmp = lt %a, %b
        sink %cmp
    """

    post = """
    main:
        %cmp = 1
        sink %cmp
    """

    _check_pre_post(pre, post)


# =============================================================================
# SIGNED COMPARISONS (slt, sgt)
# =============================================================================


def test_slt_var_var_disjoint_always_true():
    """
    slt a, b where a.hi < b.lo (signed) → always true
    a ∈ [0, 99], b ∈ [100, 200] → a < b always (signed)
    """
    pre = """
    main:
        %x = source
        %y = source
        %a = and %x, 99
        %b_base = and %y, 100
        %b = add %b_base, 100
        %cmp = slt %a, %b
        sink %cmp
    """

    post = """
    main:
        %cmp = 1
        sink %cmp
    """

    _check_pre_post(pre, post)


def test_sgt_var_var_disjoint_always_true():
    """
    sgt a, b where a.lo > b.hi (signed) → always true
    a ∈ [100, 200], b ∈ [0, 99] → a > b always (signed)
    """
    pre = """
    main:
        %x = source
        %y = source
        %a_base = and %x, 100
        %a = add %a_base, 100
        %b = and %y, 99
        %cmp = sgt %a, %b
        sink %cmp
    """

    post = """
    main:
        %cmp = 1
        sink %cmp
    """

    _check_pre_post(pre, post)


# =============================================================================
# SIGNED WRAPAROUND EDGE CASES
# =============================================================================


def test_slt_var_var_signed_wrap_no_fold():
    """
    slt a, b where a's range includes 2**255 (SIGNED_MIN) must not fold.
    a ∈ [0, 2**255], b ∈ [0, 0] → signed comparison is not constant.
    """
    pre = """
    main:
        %x = source
        %y = source
        %a = and %x, 0x8000000000000000000000000000000000000000000000000000000000000000
        %b = and %y, 0
        %cmp = slt %a, %b
        sink %cmp
    """

    # %b folds to 0, but %cmp must not fold due to signed wraparound.
    post = """
    main:
        %x = source
        %a = and 0x8000000000000000000000000000000000000000000000000000000000000000, %x
        %b = 0
        %cmp = slt %a, %b
        sink %cmp
    """

    _check_pre_post(pre, post)


# =============================================================================
# ASSERT ELIMINATION via comparison folding
# =============================================================================


def test_assert_eliminated_via_comparison_fold():
    """
    Full pattern: comparison folds to 1, assert(1) passes (nonzero), assert eliminated.
    """
    pre = """
    main:
        %x = source
        %y = source
        %a = and %x, 99
        %b_base = and %y, 100
        %b = add %b_base, 100
        %cmp = lt %a, %b
        assert %cmp
        sink %a
    """

    # cmp folds to 1, assert 1 is eliminated, %a still used by sink
    # Note: operands get canonicalized
    post = """
    main:
        %x = source
        %a = and 99, %x
        sink %a
    """

    _check_with_assert_elim(pre, post)
