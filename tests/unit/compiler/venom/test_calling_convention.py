import pytest

from tests.venom_utils import parse_venom
from vyper.venom.check_venom import (
    InvokeArityMismatch,
    InconsistentReturnArity,
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

