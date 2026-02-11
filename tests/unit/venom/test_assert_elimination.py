from tests.venom_utils import PrePostChecker
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
