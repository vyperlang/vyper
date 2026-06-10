import pytest

from tests.venom_utils import parse_venom
from vyper.compiler.settings import OptimizationLevel, VenomOptimizationFlags
from vyper.venom import run_passes_on
from vyper.venom.basicblock import IRLabel, IRVariable
from vyper.venom.call_layout import FunctionCallLayout
from vyper.venom.check_venom import (
    BumpArityError,
    DallocaArityError,
    DretReturnMixError,
    DretShapeError,
    DretShapeMismatch,
    FunctionCallLayoutError,
    GetfmpArityError,
    InconsistentReturnArity,
    InitialFmpArityError,
    InvokeArgumentCountMismatch,
    InvokeArityMismatch,
    MultiOutputNonInvoke,
    RetfmpReturnMixError,
    RetfmpShapeError,
    SetfmpArityError,
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
    _assert_raises(excinfo.value, MultiOutputNonInvoke)


def test_bump_arity_single_output_rejected():
    src = """
    function main {
    main:
        %fmp = calldatasize
        %a = bump 32, %fmp
        sink %a
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, BumpArityError)


def test_bump_arity_three_outputs_rejected():
    src = """
    function main {
    main:
        %fmp = calldatasize
        %a, %b, %c = bump 32, %fmp
        sink %a, %b, %c
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, BumpArityError)


def test_bump_arity_wrong_operand_count_rejected():
    src = """
    function main {
    main:
        %fmp = calldatasize
        %a, %b = bump %fmp
        sink %a, %b
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, BumpArityError)


def test_bump_arity_correct_accepted():
    src = """
    function main {
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
    src = """
    function f {
    main:
        %arg = param
        %fmp = param
        %p, %next_fmp = bump 32, %fmp
        sink %arg, %p, %next_fmp
    }
    """
    ctx = parse_venom(src)
    fn = ctx.get_function(IRLabel("f"))
    fn._invoke_param_count = 1

    layout = FunctionCallLayout(fn)
    assert not layout.has_return_pc_param
    assert layout.has_physical_hidden_fmp_param
    assert layout.hidden_fmp_param is not None
    assert layout.hidden_fmp_param.output == IRVariable("%fmp")
    assert [inst.output for inst in layout.user_params] == [IRVariable("%arg")]


def test_initial_fmp_arity_operand_rejected():
    src = """
    function main {
    main:
        %p = initial_fmp 1
        sink %p
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, InitialFmpArityError)


def test_initial_fmp_arity_missing_output_rejected():
    src = """
    function main {
    main:
        initial_fmp
        stop
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, InitialFmpArityError)


def test_initial_fmp_arity_multi_output_rejected():
    src = """
    function main {
    main:
        %p, %q = initial_fmp
        sink %p, %q
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, InitialFmpArityError)


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


def test_dalloca_arity_two_outputs_rejected():
    src = """
    function main {
    main:
        %p, %mark = dalloca 32
        sink %p, %mark
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, DallocaArityError)


def test_dalloca_arity_wrong_operand_count_rejected():
    src = """
    function main {
    main:
        %p, %mark = dalloca
        sink %p, %mark
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, DallocaArityError)


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


def test_multi_def_param_alias_is_demoted_not_crash():
    # Pre-SSA IR may contain multi-def variables (MakeSSA repairs them). A
    # variable assigned from two different params is simply "not a unique
    # param alias": validation must accept the IR, not crash.
    src = """
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
    ctx = parse_venom(src)
    check_calling_convention(ctx)

    layout = FunctionCallLayout(ctx.get_function(IRLabel("f")))
    assert layout.param_for_alias(IRVariable("%x")) is None
    assert layout.param_for_alias(IRVariable("%retpc")) is not None


def test_multi_def_param_alias_survives_full_pipeline():
    src = """
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
    ctx = parse_venom(src)
    flags = VenomOptimizationFlags(level=OptimizationLevel.O2)
    run_passes_on(ctx, flags, disable_mem_checks=True)


def test_dret_rejects_static_label_return_pc():
    # Per the dret spec, dret is valid only in internal functions with a
    # return-PC param. A static label return_pc must be rejected: otherwise
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
        %fmp = param
        %retpc = param
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    invoke = next(
        inst
        for bb in ctx.get_function(IRLabel("main")).get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode == "invoke"
    )
    invoke.operands = [IRLabel("f"), IRVariable("%arg"), IRVariable("%fmp")]

    callee = ctx.get_function(IRLabel("f"))
    callee._invoke_param_count = 1
    check_calling_convention(ctx)


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
    ctx.get_function(IRLabel("f"))._invoke_param_count = 2
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

    function f {
    main:
        %arg = param
        %fmp = param
        %retpc = param
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    callee = ctx.get_function(IRLabel("f"))
    callee._invoke_param_count = 1

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
    invoke = next(
        inst
        for bb in ctx.get_function(IRLabel("main")).get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode == "invoke"
    )
    invoke.operands = [IRLabel("f"), IRVariable("%arg"), IRVariable("%fmp")]

    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, InvokeArgumentCountMismatch)


def test_function_invoke_param_count_metadata_must_match_user_params():
    src = """
    function main {
    main:
        invoke @f
    }

    function f {
    main:
        %retpc = param
        ret %retpc
    }
    """
    ctx = parse_venom(src)
    callee = ctx.get_function(IRLabel("f"))
    callee._invoke_param_count = 1

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


def test_getfmp_arity_operand_rejected():
    src = """
    function main {
    main:
        %p = getfmp 1
        sink %p
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, GetfmpArityError)


def test_getfmp_arity_missing_output_rejected():
    src = """
    function main {
    main:
        getfmp
        stop
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, GetfmpArityError)


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


def test_setfmp_arity_missing_operand_rejected():
    src = """
    function main {
    main:
        setfmp
        stop
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, SetfmpArityError)


def test_setfmp_arity_output_rejected():
    src = """
    function main {
    main:
        %q = setfmp 64
        sink %q
    }
    """
    ctx = parse_venom(src)
    with pytest.raises(ExceptionGroup) as excinfo:
        check_calling_convention(ctx)
    _assert_raises(excinfo.value, SetfmpArityError)


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
