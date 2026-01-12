"""
Tests for internal function definition and call codegen.
"""
import pytest

from vyper.codegen_venom.context import VenomCodegenContext
from vyper.compiler.phases import CompilerData
from vyper.semantics.types.shortcuts import UINT256_T, INT256_T
from vyper.semantics.types.bytestrings import BytesT
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext


def _make_context_with_module(source: str) -> VenomCodegenContext:
    """Create a VenomCodegenContext from Vyper source."""
    compiler_data = CompilerData(source)
    module_t = compiler_data.global_ctx

    ctx = IRContext()
    fn = ctx.create_function("test")
    builder = VenomBuilder(ctx, fn)
    return VenomCodegenContext(module_t, builder)


def _get_internal_func(ctx: VenomCodegenContext, name: str):
    """Get internal function type from context by name."""
    for func_ast in ctx.module_ctx.function_defs:
        if func_ast.name == name:
            return func_ast._metadata["func_type"]
    raise ValueError(f"Function {name} not found")


class TestPassViaStack:
    """Test pass_via_stack helper."""

    def test_word_args_pass_via_stack(self):
        """Word-sized args should pass via stack up to limit."""
        source = """
# @version ^0.4.0

@internal
def _helper(a: uint256, b: uint256) -> uint256:
    return a + b

@external
def foo() -> uint256:
    return self._helper(1, 2)
"""
        ctx = _make_context_with_module(source)
        func_t = _get_internal_func(ctx, "_helper")

        result = ctx.pass_via_stack(func_t)
        assert result["a"] is True
        assert result["b"] is True

    def test_complex_args_pass_via_memory(self):
        """Non-word args should pass via memory."""
        source = """
# @version ^0.4.0

@internal
def _helper(data: Bytes[100]) -> uint256:
    return len(data)

@external
def foo() -> uint256:
    return self._helper(b"hello")
"""
        ctx = _make_context_with_module(source)
        func_t = _get_internal_func(ctx, "_helper")

        result = ctx.pass_via_stack(func_t)
        assert result["data"] is False

    def test_many_args_overflow_to_memory(self):
        """Args beyond MAX_STACK_ARGS should pass via memory."""
        source = """
# @version ^0.4.0

@internal
def _helper(a: uint256, b: uint256, c: uint256, d: uint256, e: uint256, f: uint256, g: uint256, h: uint256) -> uint256:
    return a + b + c + d + e + f + g + h

@external
def foo() -> uint256:
    return self._helper(1, 2, 3, 4, 5, 6, 7, 8)
"""
        ctx = _make_context_with_module(source)
        func_t = _get_internal_func(ctx, "_helper")

        result = ctx.pass_via_stack(func_t)
        # First 6 args pass via stack (MAX_STACK_ARGS=6, minus 1 for return)
        # Actually: return type takes 1 slot, so 5 args via stack
        stack_count = sum(1 for v in result.values() if v)
        memory_count = sum(1 for v in result.values() if not v)

        # At least some should be via memory
        assert memory_count >= 2


class TestReturnsStackCount:
    """Test returns_stack_count helper."""

    def test_no_return(self):
        """Void function returns 0."""
        source = """
# @version ^0.4.0

@internal
def _helper():
    pass

@external
def foo():
    self._helper()
"""
        ctx = _make_context_with_module(source)
        func_t = _get_internal_func(ctx, "_helper")

        assert ctx.returns_stack_count(func_t) == 0

    def test_word_return(self):
        """Single word return gives 1."""
        source = """
# @version ^0.4.0

@internal
def _helper() -> uint256:
    return 42

@external
def foo() -> uint256:
    return self._helper()
"""
        ctx = _make_context_with_module(source)
        func_t = _get_internal_func(ctx, "_helper")

        assert ctx.returns_stack_count(func_t) == 1

    def test_tuple_return(self):
        """Two-element word tuple returns 2."""
        source = """
# @version ^0.4.0

@internal
def _helper() -> (uint256, uint256):
    return (1, 2)

@external
def foo() -> (uint256, uint256):
    return self._helper()
"""
        ctx = _make_context_with_module(source)
        func_t = _get_internal_func(ctx, "_helper")

        assert ctx.returns_stack_count(func_t) == 2

    def test_complex_return_via_memory(self):
        """Complex types return via memory (0 stack returns)."""
        source = """
# @version ^0.4.0

@internal
def _helper() -> Bytes[100]:
    return b"hello"

@external
def foo() -> Bytes[100]:
    return self._helper()
"""
        ctx = _make_context_with_module(source)
        func_t = _get_internal_func(ctx, "_helper")

        assert ctx.returns_stack_count(func_t) == 0


class TestIsWordType:
    """Test is_word_type helper."""

    def test_uint256_is_word(self):
        """uint256 should be word type."""
        source = """
# @version ^0.4.0

@external
def foo():
    pass
"""
        ctx = _make_context_with_module(source)
        assert ctx.is_word_type(UINT256_T) is True

    def test_int256_is_word(self):
        """int256 should be word type."""
        source = """
# @version ^0.4.0

@external
def foo():
    pass
"""
        ctx = _make_context_with_module(source)
        assert ctx.is_word_type(INT256_T) is True

    def test_bytes_not_word(self):
        """Bytes[100] should not be word type."""
        source = """
# @version ^0.4.0

@external
def foo():
    pass
"""
        ctx = _make_context_with_module(source)
        bytes_t = BytesT(100)
        assert ctx.is_word_type(bytes_t) is False


class TestContextFields:
    """Test new context fields."""

    def test_max_stack_args(self):
        """MAX_STACK_ARGS should be 6."""
        source = """
# @version ^0.4.0

@external
def foo():
    pass
"""
        ctx = _make_context_with_module(source)
        assert ctx.MAX_STACK_ARGS == 6

    def test_max_stack_returns(self):
        """MAX_STACK_RETURNS should be 2."""
        source = """
# @version ^0.4.0

@external
def foo():
    pass
"""
        ctx = _make_context_with_module(source)
        assert ctx.MAX_STACK_RETURNS == 2
