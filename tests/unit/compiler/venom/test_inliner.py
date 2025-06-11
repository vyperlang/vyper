from tests.venom_utils import parse_venom
from vyper.compiler.settings import OptimizationLevel
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.check_venom import check_venom_ctx
from vyper.venom.passes import FunctionInlinerPass, SimplifyCFGPass


def test_inliner_phi_invalidation():
    """
    Test if the spliting the basic block
    which contains invoke does not create
    invalid phi which would later be
    removed by SimplifyCFGPass
    """

    pre = """
    function main {
    main:
        %p = source
        %1 = invoke @f, %p
        %2 = 0
        jmp @cond
    cond:
        %2:1 = phi @main, %2, @body, %2:2
        %cond = iszero %2:1
        jnz %cond, @body, @join
    body:
        %2:2 = add %2:1, 1
        jmp @cond
    join:
        sink %2:1
    }

    function f {
    main:
        %p = source
        %1 = add %p, 1
        ret %1
    }
    """

    ctx = parse_venom(pre)

    ir_analyses = {}
    for fn in ctx.functions.values():
        ir_analyses[fn] = IRAnalysesCache(fn)

    FunctionInlinerPass(ir_analyses, ctx, OptimizationLevel.CODESIZE).run_pass()

    for fn in ctx.get_functions():
        ac = IRAnalysesCache(fn)
        SimplifyCFGPass(ac, fn).run_pass()

    check_venom_ctx(ctx)


def test_inliner_phi_invalidation_inner():
    """
    Test if the spliting the basic block
    which contains invoke does not create
    invalid phi which would later be
    removed by SimplifyCFGPass
    """

    pre = """
    function main {
    main:
        %p = source
        jnz %p, @then, @first_join
    then:
        %a = add 1, %p
        jmp @first_join
    first_join:
        %tmp = phi @main, %p, @then, %a
        %1 = invoke @f, %tmp
        %2 = 0
        jmp @cond
    cond:
        %2:1 = phi @first_join, %2, @body, %2:2
        %cond = iszero %2:1
        jnz %cond, @body, @join
    body:
        %2:2 = add %2:1, 1
        jmp @cond
    join:
        sink %2:1
    }

    function f {
    main:
        %p = source
        %1 = add %p, 1
        ret %1
    }
    """

    ctx = parse_venom(pre)

    ir_analyses = {}
    for fn in ctx.functions.values():
        ir_analyses[fn] = IRAnalysesCache(fn)

    FunctionInlinerPass(ir_analyses, ctx, OptimizationLevel.CODESIZE).run_pass()

    for fn in ctx.get_functions():
        ac = IRAnalysesCache(fn)
        SimplifyCFGPass(ac, fn).run_pass()

    check_venom_ctx(ctx)
