import pytest

from tests.venom_utils import parse_venom
from vyper.venom.basicblock import IRLabel, IRVariable
from vyper.venom.check_venom import (
    BumpArityError,
    FunctionCallLayoutError,
    InconsistentReturnArity,
    InvokeArgumentCountMismatch,
    InvokeArityMismatch,
    MultiOutputNonInvoke,
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
    callee._has_fmp_param = True
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
    callee._has_fmp_param = True

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
