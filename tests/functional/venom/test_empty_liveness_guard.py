from tests.venom_utils import parse_venom
from vyper.compiler.settings import OptimizationLevel
from vyper.venom import generate_assembly_experimental, run_passes_on


def test_empty_liveness_at_function_entry_param_then_stop():
    venom = """
    function main {
    main:
        %a = param
        %b = param
        stop
    }
    """
    ctx = parse_venom(venom)
    run_passes_on(ctx, OptimizationLevel.GAS)
    generate_assembly_experimental(ctx)


def test_empty_liveness_param_then_revert_immediates():
    venom = """
    function main {
    main:
        %p = param
        revert 0, 0
    }
    """
    ctx = parse_venom(venom)
    run_passes_on(ctx, OptimizationLevel.GAS)
    generate_assembly_experimental(ctx)
