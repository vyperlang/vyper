from tests.venom_utils import assert_ctx_eq, parse_venom
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import SCCP, SimplifyCFGPass


def test_phi_reduction_after_block_pruning():
    pre = """
    function _global {
        _global:
            jnz 1, @then, @else
        then:
            %1 = 1
            jmp @join
        else:
            %2 = 2
            jmp @join
        join:
            %3 = phi @then, %1, @else, %2
            stop
    }
    """
    post = """
    function _global {
        _global:
            %1 = 1
            %3 = %1
            stop
    }
    """
    ctx1 = parse_venom(pre)
    for fn in ctx1.functions.values():
        ac = IRAnalysesCache(fn)
        SCCP(ac, fn).run_pass()
        SimplifyCFGPass(ac, fn).run_pass()

    ctx2 = parse_venom(post)
    assert_ctx_eq(ctx1, ctx2)
