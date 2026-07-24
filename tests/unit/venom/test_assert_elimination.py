from tests.venom_utils import PrePostChecker
from vyper.venom.analysis.variable_range.value_range import UNSIGNED_MAX
from vyper.venom.passes.assert_elimination import AssertEliminationPass
from vyper.venom.passes.remove_unused_variables import RemoveUnusedVariablesPass

_check_pre_post = PrePostChecker([AssertEliminationPass, RemoveUnusedVariablesPass])


def test_remove_overflow_assert():
    pre = """
    main:
        %input = source
        %len = mod %input, 1000
        %scaled = shl 5, %len
        %target = add 4096, %scaled
        %overflow = lt %target, 4096
        %ok = iszero %overflow
        assert %ok
        sink %target
    """

    post = """
    main:
        %input = source
        %len = mod %input, 1000
        %scaled = shl 5, %len
        %target = add 4096, %scaled
        sink %target
    """

    _check_pre_post(pre, post)


def _check_signed_division_assert_kept(opcode):
    mask = UNSIGNED_MAX - 31  # includes the signed word -32
    pre = f"""
    main:
        %input = source
        %x = and %input, {mask}
        %result = {opcode} %x, 10
        %ok = sgt %result, -1
        assert %ok
        sink %result
    """

    _check_pre_post(pre, pre)


def test_keep_sdiv_sign_boundary_assert():
    _check_signed_division_assert_kept("sdiv")


def test_keep_smod_sign_boundary_assert():
    _check_signed_division_assert_kept("smod")
