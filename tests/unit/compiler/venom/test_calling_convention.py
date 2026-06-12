import pytest

from tests.venom_utils import find_inst, parse_venom
from vyper.compiler.settings import OptimizationLevel, VenomOptimizationFlags
from vyper.venom import run_passes_on
from vyper.venom.basicblock import IRLabel, IRVariable
from vyper.venom.call_layout import FunctionCallLayout
from vyper.venom.check_venom import (
    DretReturnMixError,
    DretShapeError,
    DretShapeMismatch,
    FmpAnnotationError,
    FunctionCallLayoutError,
    InconsistentReturnArity,
    InvokeArgumentCountMismatch,
    InvokeArityMismatch,
    MixedFmpIRError,
    MultiOutputNotAllowed,
    ParamLayoutError,
    RetfmpReturnMixError,
    RetfmpShapeError,
    check_calling_convention,
)


def _assert_raises(exc_group, exc_type):
    assert any(isinstance(err, exc_type) for err in exc_group.exceptions)


def test_invoke_arity_match_zero():
    src = """
    function main {
    main:
        %p = source
        invoke @f, %p
    }

    function f {
    main:
        %p = param
        ret @retpc
    }
    """
    ctx = parse_venom(src)
    # Should not raise: callee returns 0, call site binds 0
    check_calling_convention(ctx)


def test_invoke_arity_match_one():
    src = """
    function main {
    main:
        %p = source
        %ret = invoke @f, %p
        sink %ret
    }

    function f {
    main:
        %p = param
        %one = add %p, 1
        ret %one, @retpc
    }
    """
    ctx = parse_venom(src)
    # Should not raise: callee returns 1, call site binds 1
    check_calling_convention(ctx)


def test_invoke_arity_mismatch_too_few_outputs():
    src = """
    function main {
    main:
        %p = source
        invoke @f, %p
    }

    function f {
    main:
        %p = param
        %one = add %p, 1
        ret %one, @retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, InvokeArityMismatch)


def test_invoke_arity_mismatch_too_many_outputs():
    src = """
    function main {
    main:
        %p = source
        %ret = invoke @f, %p
        sink %ret
    }

    function f {
    main:
        %p = param
        ret @retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, InvokeArityMismatch)


def test_inconsistent_callee_return_arity():
    src = """
    function main {
    main:
        %p = source
        invoke @f, %p
    }

    function f {
    entry:
        %p = param
        jnz %p, @then, @else
    then:
        %one = add %p, 1
        ret %one, @retpc
    else:
        ret @retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, InconsistentReturnArity)


def test_inconsistent_callee_return_arity_no_spurious_mismatch():
    # When callee has inconsistent return arity, we should only report
    # InconsistentReturnArity, not InvokeArityMismatch for the call site.
    src = """
    function main {
    main:
        %p = source
        %ret = invoke @f, %p
        sink %ret
    }

    function f {
    entry:
        %p = param
        jnz %p, @then, @else
    then:
        %one = add %p, 1
        ret %one, @retpc
    else:
        ret @retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, InconsistentReturnArity)
    assert not any(isinstance(err, InvokeArityMismatch) for err in excinfo.value.exceptions)


def test_multi_lhs_non_invoke_rejected():
    src = """
    function main {
    main:
        %x, %y = add 1, 2
        sink %x, %y
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, MultiOutputNotAllowed)


@pytest.mark.parametrize(
    ("opcode", "body"),
    [
        # bump must have exactly 2 operands and 2 outputs
        ("bump", "%fmp = calldatasize\n        %a = bump 32, %fmp\n        sink %a"),
        (
            "bump",
            "%fmp = calldatasize\n        %a, %b, %c = bump 32, %fmp\n        sink %a, %b, %c",
        ),
        ("bump", "%fmp = calldatasize\n        %a, %b = bump %fmp\n        sink %a, %b"),
        # initial_fmp must have exactly 0 operands and 1 output
        ("initial_fmp", "%p = initial_fmp 1\n        sink %p"),
        ("initial_fmp", "initial_fmp\n        stop"),
        ("initial_fmp", "%p, %q = initial_fmp\n        sink %p, %q"),
        # dalloca must have exactly 1 operand and 1 output
        ("dalloca", "%p, %mark = dalloca 32\n        sink %p, %mark"),
        ("dalloca", "%p, %mark = dalloca\n        sink %p, %mark"),
        # getfmp must have exactly 0 operands and 1 output
        ("getfmp", "%p = getfmp 1\n        sink %p"),
        ("getfmp", "getfmp\n        stop"),
        # setfmp must have exactly 1 operand and 0 outputs
        ("setfmp", "setfmp\n        stop"),
        ("setfmp", "%q = setfmp 64\n        sink %q"),
    ],
)
def test_fmp_opcode_arity_violations_rejected(opcode, body):
    src = f"""
    function main {{
    main:
        {body}
    }}
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    # assert on the validation outcome rather than a concrete error class:
    # an arity diagnostic naming the offending opcode must be reported
    assert any("arity" in str(err) and opcode in str(err) for err in excinfo.value.exceptions)


def test_bump_arity_correct_accepted():
    src = """
    function main [fmp_lowered] {
    main:
        %fmp = calldatasize
        %a, %b = bump 32, %fmp
        sink %a, %b
    }
    """
    ctx = parse_venom(src)
    # Should not raise: bump has 2 operands and 2 outputs.
    check_calling_convention(ctx)


def test_function_layout_detects_hidden_fmp_without_return_pc():
    # the hidden FMP param is named by its dedicated opcode; the layout
    # facts are purely syntactic (no return-PC param exists here)
    src = """
    function f [fmp_lowered] {
    main:
        %arg = param
        %fmp = fmp_param
        %p, %next_fmp = bump 32, %fmp
        sink %arg, %p, %next_fmp
    }
    """
    ctx = parse_venom(src)
    fn = ctx.get_function(IRLabel("f"))

    layout = FunctionCallLayout(fn)
    assert not layout.has_return_pc_param
    assert layout.has_physical_hidden_fmp_param
    assert layout.hidden_fmp_param is not None
    assert layout.hidden_fmp_param.output == IRVariable("%fmp")
    assert [inst.output for inst in layout.user_params] == [IRVariable("%arg")]


def test_dalloca_arity_single_output_accepted():
    src = """
    function main {
    main:
        %p = dalloca 32
        sink %p
    }
    """
    ctx = parse_venom(src)
    check_calling_convention(ctx)


def test_dret_shape_accepted():
    src = """
    function main {
    main:
        %ret = invoke @f
        sink %ret
    }

    function f {
    main:
        %retpc = param
        %p = source
        dret 1, %p, 32, %retpc
    }
    """
    ctx = parse_venom(src)
    check_calling_convention(ctx)


def test_dret_rejects_zero_dynamic_count():
    src = """
    function main {
    main:
        invoke @f
    }

    function f {
    main:
        %retpc = param
        dret 0, %retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, DretShapeError)


def test_dret_rejects_non_return_pc_tail():
    src = """
    function main {
    main:
        %ret = invoke @f
        sink %ret
    }

    function f {
    main:
        %p = source
        dret 1, %p, 32, 0
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, DretShapeError)


def test_dret_rejects_inconsistent_shapes():
    src = """
    function main {
    main:
        %ret = invoke @f
        sink %ret
    }

    function f {
    entry:
        %retpc = param
        %cond = source
        %p = source
        jnz %cond, @left, @right
    left:
        dret 1, %p, 32, %retpc
    right:
        %ordinary = source
        dret 1, %ordinary, %p, 32, %retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, DretShapeMismatch)


def test_dret_rejects_mixing_ret_and_dret():
    src = """
    function main {
    main:
        invoke @f
    }

    function f {
    entry:
        %retpc = param
        %cond = source
        %p = source
        jnz %cond, @left, @right
    left:
        dret 1, %p, 32, %retpc
    right:
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, DretReturnMixError)


# a caller invoking `f`, whose `%x` is assigned from two different params
# (legal pre-SSA IR; MakeSSA repairs the multi-def)
_MULTI_DEF_PARAM_ALIAS_SRC = """
function main {
main:
    %a = source
    %b = source
    invoke @f, %a, %b
    stop
}

function f {
main:
    %p1 = param
    %p2 = param
    %retpc = param
    %x = %p1
    %x = %p2
    mstore 0, %x
    ret %retpc
}
"""


def test_multi_def_param_alias_is_demoted_not_crash():
    # Pre-SSA IR may contain multi-def variables (MakeSSA repairs them). A
    # variable assigned from two different params is simply "not a unique
    # param alias": validation must accept the IR, not crash.
    ctx = parse_venom(_MULTI_DEF_PARAM_ALIAS_SRC)
    check_calling_convention(ctx)

    layout = FunctionCallLayout(ctx.get_function(IRLabel("f")))
    assert layout.param_for_alias(IRVariable("%x")) is None
    assert layout.param_for_alias(IRVariable("%retpc")) is not None


def test_multi_def_param_alias_survives_full_pipeline():
    ctx = parse_venom(_MULTI_DEF_PARAM_ALIAS_SRC)
    flags = VenomOptimizationFlags(level=OptimizationLevel.O2)
    run_passes_on(ctx, flags, disable_mem_checks=True)


def test_dret_rejects_static_label_return_pc():
    # dret is valid only in internal functions with a return-PC param.
    # A static label return_pc must be rejected: otherwise
    # the lowered convention conjures an FMP param that pops the caller's return PC
    # at runtime (silent corruption).
    src = """
    function main {
    main:
        %ret = invoke @f
        sink %ret
    }

    function f {
    entry:
        %p = dalloca 64
        mstore %p, 42
        dret 1, %p, 32, @exit
    exit:
        stop
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, DretShapeError)


def test_invoke_argument_count_mismatch_too_few_inputs():
    src = """
    function main {
    main:
        invoke @f
    }

    function f {
    main:
        %p = param
        %retpc = param
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, InvokeArgumentCountMismatch)


def test_invoke_argument_count_mismatch_too_many_inputs():
    src = """
    function main {
    main:
        %p = source
        %q = source
        invoke @f, %p, %q
    }

    function f {
    main:
        %p = param
        %retpc = param
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, InvokeArgumentCountMismatch)


def test_invoke_argument_count_accepts_literal_return_label():
    src = """
    function main {
    main:
        %p = source
        invoke @f, %p
    }

    function f {
    main:
        %p = param
        ret @retpc
    }
    """
    ctx = parse_venom(src)
    check_calling_convention(ctx)


def test_invoke_argument_count_accepts_hidden_fmp_tail():
    # an invoke carrying the hidden FMP operand is only legal in an
    # already-lowered (annotated) caller (FmpLoweringPass is the sole writer
    # of that operand for everything else), so the caller threads its own
    # hidden FMP param here.
    src = """
    function caller [fmp_lowered] {
    caller:
        %arg = param
        %fmp = fmp_param
        %retpc = retpc_param
        invoke @f, %arg
        ret %retpc
    }

    function f [fmp_lowered] {
    main:
        %arg = param
        %fmp = fmp_param
        %retpc = retpc_param
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    invoke = find_inst(ctx.get_function(IRLabel("caller")), "invoke")
    invoke.operands = [IRLabel("f"), IRVariable("%arg"), IRVariable("%fmp")]

    check_calling_convention(ctx)


def test_invoke_hidden_fmp_tail_rejected_in_raw_caller():
    # half-lowered (mixed raw/lowered) IR: an invoke already carrying the
    # hidden FMP operand inside a function that FmpLoweringPass will thread
    # (a raw caller) must be rejected up front -- this makes the pass's
    # assert-and-set panic unreachable from validated input.
    src = """
    function main {
    main:
        %arg = source
        %fmp = source
        invoke @f, %arg
        stop
    }

    function f [fmp_lowered] {
    main:
        %arg = param
        %fmp = fmp_param
        %retpc = retpc_param
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    invoke = find_inst(ctx.get_function(IRLabel("main")), "invoke")
    invoke.operands = [IRLabel("f"), IRVariable("%arg"), IRVariable("%fmp")]

    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, MixedFmpIRError)


def test_function_layout_counts_non_contiguous_params():
    src = """
    function main {
    main:
        %a = source
        %b = source
        %ret = invoke @f, %a, %b
        sink %ret
    }

    function f {
    main:
        %a = param
        %tmp = alloca 32
        mstore %tmp, %a
        %b = param
        %retpc = param
        ret %retpc, %b
    }
    """
    ctx = parse_venom(src)
    check_calling_convention(ctx)


def test_function_layout_infers_copied_return_pc_param():
    src = """
    function main {
    main:
        %arg = source
        %ret = invoke @f, %arg
        sink %ret
    }

    function f {
    main:
        %arg = param
        %retpc = param
        %retpc_copy = %retpc
        ret %retpc_copy, %arg
    }
    """
    ctx = parse_venom(src)
    check_calling_convention(ctx)


def test_invoke_argument_count_rejects_missing_hidden_fmp_tail():
    src = """
    function main {
    main:
        %arg = source
        invoke @f, %arg
    }

    function f [fmp_lowered] {
    main:
        %arg = param
        %fmp = fmp_param
        %retpc = retpc_param
        ret %retpc
    }
    """
    ctx = parse_venom(src)

    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, InvokeArgumentCountMismatch)


def test_invoke_argument_count_rejects_stale_hidden_fmp_tail():
    src = """
    function main {
    main:
        %arg = source
        %fmp = source
        invoke @f, %arg
    }

    function f {
    main:
        %arg = param
        %retpc = param
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    invoke = find_inst(ctx.get_function(IRLabel("main")), "invoke")
    invoke.operands = [IRLabel("f"), IRVariable("%arg"), IRVariable("%fmp")]

    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, InvokeArgumentCountMismatch)


def test_return_pc_param_must_be_final():
    # raw-level definition: the return PC is the param the rets anchor; it
    # must occupy the final (top-of-stack) param slot
    src = """
    function main {
    main:
        %a = source
        invoke @f, %a
    }

    function f {
    main:
        %retpc = param
        %a = param
        ret %retpc
    }
    """
    ctx = parse_venom(src)

    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, FunctionCallLayoutError)


def test_getfmp_arity_correct_accepted():
    src = """
    function main {
    main:
        %p = getfmp
        sink %p
    }
    """
    ctx = parse_venom(src)
    check_calling_convention(ctx)


def test_setfmp_arity_correct_accepted():
    src = """
    function main {
    main:
        %p = getfmp
        setfmp %p
        stop
    }
    """
    ctx = parse_venom(src)
    check_calling_convention(ctx)


def test_retfmp_shape_accepted():
    src = """
    function main {
    main:
        %ret = invoke @f
        sink %ret
    }

    function f {
    main:
        %retpc = param
        %p = source
        retfmp %p, %retpc
    }
    """
    ctx = parse_venom(src)
    check_calling_convention(ctx)


def test_retfmp_rejects_non_return_pc_tail():
    # like dret, retfmp publishes the FMP to the caller, which is only
    # meaningful in internal functions with a return-PC param
    src = """
    function main {
    main:
        %ret = invoke @f
        sink %ret
    }

    function f {
    main:
        %p = source
        retfmp %p, 0
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, RetfmpShapeError)


def test_retfmp_rejects_static_label_return_pc():
    src = """
    function main {
    main:
        %ret = invoke @f
        sink %ret
    }

    function f {
    entry:
        %p = source
        retfmp %p, @exit
    exit:
        stop
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, RetfmpShapeError)


def test_retfmp_rejects_mixing_with_ret():
    src = """
    function main {
    main:
        %ret = invoke @f
        sink %ret
    }

    function f {
    entry:
        %retpc = param
        %cond = source
        %p = source
        jnz %cond, @left, @right
    left:
        retfmp %p, %retpc
    right:
        ret %retpc, %p
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, RetfmpReturnMixError)


def test_retfmp_rejects_mixing_with_dret():
    # a function with both raw `dret` and `retfmp` is half-desugared
    src = """
    function main {
    main:
        %ret = invoke @f
        sink %ret
    }

    function f {
    entry:
        %retpc = param
        %cond = source
        %p = source
        jnz %cond, @left, @right
    left:
        retfmp %p, %retpc
    right:
        dret 1, %p, 32, %retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, RetfmpReturnMixError)


def test_fmp_param_canonical_position_accepted():
    src = """
    function main {
    main:
        stop
    }

    function f [fmp_lowered] {
    f:
        %a = param
        %fmp = fmp_param
        %retpc = retpc_param
        %p, %next = bump 32, %fmp
        mstore %p, %a
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    check_calling_convention(ctx)


@pytest.mark.parametrize(
    "params",
    [
        # plain param after fmp_param
        "%fmp = fmp_param\n        %a = param\n        %retpc = retpc_param",
        # fmp_param after retpc_param
        "%a = param\n        %retpc = retpc_param\n        %fmp = fmp_param",
        # duplicate fmp_param
        "%fmp = fmp_param\n        %fmp2 = fmp_param\n        %retpc = retpc_param",
        # duplicate retpc_param
        "%fmp = fmp_param\n        %retpc = retpc_param\n        %retpc2 = retpc_param",
    ],
)
def test_fmp_param_position_violations_rejected(params):
    src = f"""
    function main {{
    main:
        stop
    }}

    function f [fmp_lowered] {{
    f:
        {params}
        ret %retpc
    }}
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, ParamLayoutError)


def test_fmp_param_outside_entry_block_rejected():
    src = """
    function main {
    main:
        stop
    }

    function f [fmp_lowered] {
    f:
        %retpc = retpc_param
        jmp @body
    body:
        %fmp = fmp_param
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, ParamLayoutError)


def test_mixed_raw_ops_with_fmp_param_rejected():
    # a function containing raw FMP opcodes may not also carry the lowered
    # convention (half-lowered IR is rejected, not tolerated)
    src = """
    function main {
    main:
        stop
    }

    function f {
    f:
        %fmp = fmp_param
        %retpc = retpc_param
        %p = dalloca 32
        mstore %p, 1
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, MixedFmpIRError)


def test_mixed_raw_ops_with_bump_rejected():
    src = """
    function main {
    main:
        %fmp = calldatasize
        %a, %b = bump 32, %fmp
        %p = dalloca 32
        sink %a, %b, %p
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, MixedFmpIRError)


# ---------------------------------------------------------------------------
# annotation-level validation: the calling convention is carried only by
# syntax (opcodes) and the explicit `[fmp_lowered(, fmp_publishes)?]`
# function-header annotation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        # bump without annotation
        "%fmp = calldatasize\n        %a, %b = bump 32, %fmp\n        sink %a, %b",
        # initial_fmp without annotation
        "%fmp = initial_fmp\n        sink %fmp",
    ],
)
def test_lowered_artifacts_require_annotation(body):
    src = f"""
    function main {{
    main:
        {body}
    }}
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, FmpAnnotationError)


def test_fmp_param_requires_annotation():
    src = """
    function main {
    main:
        stop
    }

    function f {
    f:
        %fmp = fmp_param
        %retpc = retpc_param
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, FmpAnnotationError)


def test_retpc_param_is_level_neutral():
    # `retpc_param` is just a syntactic name for the return-PC slot: the
    # frontend emits it in RAW IR (so even no-ret functions are
    # self-describing); it requires no annotation and may coexist with raw
    # FMP opcodes.
    src = """
    function main {
    main:
        %ret = invoke @f
        sink %ret
    }

    function f {
    f:
        %retpc = retpc_param
        %p = dalloca 32
        mstore %p, 7
        dret 1, %p, 32, %retpc
    }
    """
    ctx = parse_venom(src)
    check_calling_convention(ctx)


def test_annotated_function_with_raw_ops_rejected():
    # an annotated (lowered) function may not contain raw FMP opcodes
    src = """
    function main {
    main:
        stop
    }

    function f [fmp_lowered] {
    f:
        %retpc = retpc_param
        %p = dalloca 32
        mstore %p, 1
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, MixedFmpIRError)


def test_annotated_publishing_function_shape_accepted():
    # lowered publishing convention: ret operands are
    # [user returns..., adopted FMP, return_pc]; the (lowered) caller binds
    # the extra hidden output
    src = """
    function main [fmp_lowered] {
    main:
        %v, %fmp = invoke @f
        sink %v, %fmp
    }

    function f [fmp_lowered, fmp_publishes] {
    f:
        %retpc = retpc_param
        %base = initial_fmp
        %p, %new = bump 32, %base
        ret %p, %new, %retpc
    }
    """
    ctx = parse_venom(src)
    check_calling_convention(ctx)

    fn = ctx.get_function(IRLabel("f"))
    assert fn._fmp_signature is not None
    assert fn._fmp_signature.publishes is True
    assert fn._fmp_signature.has_fmp_param is False


def test_publishing_lowered_callee_rejected_in_raw_caller():
    # the hidden adopted-FMP output of a publishing lowered callee is part
    # of the lowered convention; a raw caller cannot legally bind it
    # (FmpLoweringPass alone writes hidden invoke outputs)
    src = """
    function main {
    main:
        %v, %fmp = invoke @f
        mstore 0, %v
        return 0, 32
    }

    function f [fmp_lowered, fmp_publishes] {
    f:
        %retpc = retpc_param
        %base = initial_fmp
        %p, %new = bump 32, %base
        ret %p, %new, %retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, MixedFmpIRError)


def test_annotated_publishes_without_hidden_ret_value_rejected():
    # the annotation claims the rets carry a hidden adopted-FMP value; a
    # bare `ret %retpc` cannot
    src = """
    function main {
    main:
        stop
    }

    function f [fmp_lowered, fmp_publishes] {
    f:
        %retpc = retpc_param
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, FmpAnnotationError)


def test_annotated_function_with_plain_param_retpc_rejected():
    # lowered IR carries its convention in opcodes only: ret-anchored
    # return-PC discovery is a raw-level definition, so an annotated
    # function whose ret anchors a plain `param` is malformed
    src = """
    function main {
    main:
        stop
    }

    function f [fmp_lowered] {
    f:
        %retpc = param
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, FmpAnnotationError)


def test_unknown_annotation_rejected():
    src = """
    function main [fmp_bogus] {
    main:
        stop
    }
    """
    with pytest.raises(ValueError, match="unknown function annotation"):
        parse_venom(src)


def test_publishes_annotation_requires_lowered():
    src = """
    function main [fmp_publishes] {
    main:
        stop
    }
    """
    with pytest.raises(ValueError, match="requires `fmp_lowered`"):
        parse_venom(src)


def test_duplicate_annotation_rejected():
    src = """
    function main [fmp_lowered, fmp_lowered] {
    main:
        stop
    }
    """
    with pytest.raises(ValueError, match="duplicate function annotation"):
        parse_venom(src)
