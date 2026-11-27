import re

import pytest

from tests.venom_utils import stack_spilling_inf_source
from vyper.compiler import compile_code
from vyper.compiler.settings import OptimizationLevel, Settings, VenomOptimizationFlags
from vyper.venom import run_passes_on
from vyper.venom.check_venom import (
    EomFrameError,
    InitialFmpBoundError,
    StaticFrameError,
    check_venom_ctx,
    find_semantic_errors,
)
from vyper.venom.parser import parse_venom


def _frame_errors(ctx) -> list[StaticFrameError]:
    return [e for e in find_semantic_errors(ctx) if isinstance(e, StaticFrameError)]


def _sum_words_source() -> str:
    # the internal call spills at O1, so the stack spiller places its slots
    # at the largest `eom`
    params = ", ".join(f"a{i}: uint256" for i in range(16))
    args = ", ".join(f"a{i}" for i in range(16))
    total = " + ".join(f"a{i}" for i in range(16))
    return f"""
@internal
def sum_words({params}) -> uint256:
    return {total}

@external
def foo({params}) -> uint256:
    return self.sum_words({args})
    """


def _lowered(source: str, level: OptimizationLevel) -> str:
    settings = Settings(experimental_codegen=True, optimize=level)
    return str(compile_code(source, output_formats=["ir_runtime"], settings=settings)["ir_runtime"])


@pytest.mark.parametrize(
    "level", [OptimizationLevel.O1, OptimizationLevel.O2, OptimizationLevel.CODESIZE]
)
@pytest.mark.parametrize("source", [_sum_words_source(), stack_spilling_inf_source()])
def test_round_tripped_frame_accepted(source, level):
    # the frame bounds the pipeline itself prints must pass the check
    lowered = _lowered(source, level)
    assert "eom=" in lowered
    ctx = parse_venom(lowered)
    assert find_semantic_errors(ctx) == []


def test_forged_eom_rejected():
    # issue 5398: the same body with `eom` lowered below its static frame
    # would place spill slots inside the frame
    lowered = _lowered(_sum_words_source(), OptimizationLevel.O1)
    assert "function runtime [fmp_lowered, eom=544]" in lowered

    forged = lowered.replace("eom=544", "eom=1")
    errors = _frame_errors(parse_venom(forged))
    assert len(errors) == 1
    assert isinstance(errors[0], EomFrameError)
    assert errors[0].function.name.value == "runtime"
    assert "accessed up to 544" in str(errors[0])

    # the check is tight: the frame ends exactly at 544
    errors = _frame_errors(parse_venom(lowered.replace("eom=544", "eom=543")))
    assert len(errors) == 1 and isinstance(errors[0], EomFrameError)

    # every function's `eom` is checked
    all_forged = re.sub(r"eom=\d+", "eom=1", lowered)
    errors = _frame_errors(parse_venom(all_forged))
    assert len(errors) == 2
    assert all(isinstance(e, EomFrameError) for e in errors)

    # the pipeline entry point rejects it too, not only check_venom_ctx
    with pytest.raises(ExceptionGroup) as excinfo:
        run_passes_on(parse_venom(forged), VenomOptimizationFlags(level=OptimizationLevel.O1))
    assert any(isinstance(e, EomFrameError) for e in excinfo.value.exceptions)


def test_eom_without_static_accesses_accepted():
    ctx = parse_venom("""
    function main [fmp_lowered, eom=0] {
      main:
        %x = calldataload 0
        sink %x
    }
    """)
    assert find_semantic_errors(ctx) == []


_INITIAL_FMP_SRC = """
function main [fmp_lowered, eom=64] {
  main:
    %z = 0
    %ninety = 99
    mstore %z, %ninety
    %init = initial_fmp BOUND
    %base, %ptr = bump 32, %init
    %seven = 7
    mstore %base, %seven
    %sz = 32
    return %z, %sz
}
"""


@pytest.mark.parametrize("bound", [32, 64, 96])
def test_initial_fmp_bound_accepted(bound):
    ctx = parse_venom(_INITIAL_FMP_SRC.replace("BOUND", str(bound)))
    check_venom_ctx(ctx)


@pytest.mark.parametrize("bound", [0, 31])
def test_initial_fmp_bound_below_frame_rejected(bound):
    # issue 5399: a bound below the static frame lets `bump` hand out
    # memory that aliases the word at 0
    ctx = parse_venom(_INITIAL_FMP_SRC.replace("BOUND", str(bound)))
    with pytest.raises(ExceptionGroup) as excinfo:
        check_venom_ctx(ctx)
    errors = excinfo.value.exceptions
    assert len(errors) == 1
    assert isinstance(errors[0], InitialFmpBoundError)
    assert f"bound {bound} is below static memory accessed up to 32" in str(errors[0])


def test_initial_fmp_bound_ignores_unreachable_accesses():
    # static memory accessed only before the root's block is dead once the
    # root runs, so it does not constrain the bound (as in FmpLoweringPass)
    ctx = parse_venom("""
    function main [fmp_lowered, eom=96] {
      main:
        %a = 64
        %x = calldataload 0
        mstore %a, %x
        jmp @next
      next:
        %init = initial_fmp 0
        %base, %ptr = bump 32, %init
        mstore %base, 7
        return %base, 32
    }
    """)
    assert _frame_errors(ctx) == []


def test_initial_fmp_bound_covers_callee_frame():
    src = """
    function main [fmp_lowered, eom=96] {
      main:
        %init = initial_fmp BOUND
        %base, %ptr = bump 32, %init
        mstore %base, 7
        invoke @f
        return %base, 32
    }

    function f [fmp_lowered, eom=96] {
      main:
        %retpc = retpc_param
        %a = 64
        mstore %a, 1
        ret %retpc
    }
    """
    assert _frame_errors(parse_venom(src.replace("BOUND", "96"))) == []

    errors = _frame_errors(parse_venom(src.replace("BOUND", "64")))
    assert len(errors) == 1
    assert isinstance(errors[0], InitialFmpBoundError)
    assert "accessed up to 96" in str(errors[0])
