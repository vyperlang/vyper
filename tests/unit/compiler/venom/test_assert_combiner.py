import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import AssertCombinerPass, RemoveUnusedVariablesPass

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker([AssertCombinerPass, RemoveUnusedVariablesPass])


def test_combine_adjacent_asserts():
    pre = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        %3 = source
        %4 = iszero %3
        assert %4
        sink %3
    """

    post = """
    main:
        %1 = source
        %3 = source
        %5 = or %3, %1
        %6 = iszero %5
        assert %6
        sink %3
    """
    _check_pre_post(pre, post)


def test_skip_non_boolean_asserts():
    pre = """
    main:
        %1 = 2
        assert %1
        %2 = source
        %3 = iszero %2
        assert %3
        sink %2
    """

    post = """
    main:
        %1 = 2
        assert %1
        %2 = source
        %3 = iszero %2
        assert %3
        sink %2
    """
    _check_pre_post(pre, post)
