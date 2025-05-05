from tests.venom_utils import PrePostChecker
from vyper.venom.passes import PhiEliminationPass

_check_pre_post = PrePostChecker([PhiEliminationPass])


def test_phi_elim_loop():
    pre = """
    main:
        %v = param
        jmp @loop
    loop:
        %v:2 = phi @main, %v, @loop, %v:2
        jmp @loop
    """

    post = """
    main:
        %v = param
        jmp @loop
    loop:
        %v:2 = %v
        jmp @loop
    """

    _check_pre_post(pre, post)
