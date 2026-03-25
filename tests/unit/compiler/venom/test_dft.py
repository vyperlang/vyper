from tests.venom_utils import PrePostChecker
from vyper.venom.passes import DFTPass

_check_pre_post = PrePostChecker([DFTPass])


def _check_no_change(pre):
    _check_pre_post(pre, pre)


def test_dft():
    """
    Basic test for dft pass
    """
    pre = """
    main:
        %x = 1
        %y = 2
        return %x, %y
    """
    post = """
    main:
        %y = 2
        %x = 1
        return %x, %y
    """
    _check_pre_post(pre, post)
