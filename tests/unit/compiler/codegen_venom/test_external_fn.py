"""
Tests for external function codegen and selector dispatch.
"""
import pytest

from vyper.codegen_venom.module import VenomModuleCompiler, generate_ir_for_module
from vyper.compiler.phases import CompilerData


def _get_module_t(source: str):
    """Get module type from source."""
    compiler_data = CompilerData(source)
    return compiler_data.global_ctx


class TestVenomModuleCompiler:
    """Test VenomModuleCompiler class."""

    def test_compile_simple_function(self):
        """Test compiling a simple external function."""
        source = """
# @version ^0.4.0

@external
def foo() -> uint256:
    return 42
"""
        module_t = _get_module_t(source)
        compiler = VenomModuleCompiler(module_t)
        deploy_ctx, runtime_ctx = compiler.compile()

        # Should have created IR contexts
        assert deploy_ctx is not None
        assert runtime_ctx is not None

        # Runtime should have a function
        assert len(runtime_ctx.functions) >= 1

    def test_compile_function_with_args(self):
        """Test compiling a function with arguments."""
        source = """
# @version ^0.4.0

@external
def add(a: uint256, b: uint256) -> uint256:
    return a + b
"""
        module_t = _get_module_t(source)
        compiler = VenomModuleCompiler(module_t)
        deploy_ctx, runtime_ctx = compiler.compile()

        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_compile_multiple_functions(self):
        """Test compiling multiple external functions."""
        source = """
# @version ^0.4.0

@external
def foo() -> uint256:
    return 1

@external
def bar() -> uint256:
    return 2
"""
        module_t = _get_module_t(source)
        compiler = VenomModuleCompiler(module_t)
        deploy_ctx, runtime_ctx = compiler.compile()

        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_compile_with_fallback(self):
        """Test compiling with a fallback function."""
        source = """
# @version ^0.4.0

@external
def foo() -> uint256:
    return 42

@external
def __default__():
    pass
"""
        module_t = _get_module_t(source)
        compiler = VenomModuleCompiler(module_t)
        deploy_ctx, runtime_ctx = compiler.compile()

        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_compile_payable_function(self):
        """Test compiling a payable function."""
        source = """
# @version ^0.4.0

@external
@payable
def deposit():
    pass
"""
        module_t = _get_module_t(source)
        compiler = VenomModuleCompiler(module_t)
        deploy_ctx, runtime_ctx = compiler.compile()

        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_compile_with_kwargs(self):
        """Test compiling a function with keyword arguments."""
        source = """
# @version ^0.4.0

@external
def foo(a: uint256, b: uint256 = 10) -> uint256:
    return a + b
"""
        module_t = _get_module_t(source)
        compiler = VenomModuleCompiler(module_t)
        deploy_ctx, runtime_ctx = compiler.compile()

        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_compile_with_internal_function(self):
        """Test compiling with internal function calls."""
        source = """
# @version ^0.4.0

@internal
def _helper(x: uint256) -> uint256:
    return x * 2

@external
def foo(a: uint256) -> uint256:
    return self._helper(a)
"""
        module_t = _get_module_t(source)
        compiler = VenomModuleCompiler(module_t)
        deploy_ctx, runtime_ctx = compiler.compile()

        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_compile_with_storage(self):
        """Test compiling with storage variables."""
        source = """
# @version ^0.4.0

value: uint256

@external
def get() -> uint256:
    return self.value

@external
def set(x: uint256):
    self.value = x
"""
        module_t = _get_module_t(source)
        compiler = VenomModuleCompiler(module_t)
        deploy_ctx, runtime_ctx = compiler.compile()

        assert deploy_ctx is not None
        assert runtime_ctx is not None


class TestGenerateIRForModule:
    """Test generate_ir_for_module function."""

    def test_simple_module(self):
        """Test generating IR for a simple module."""
        source = """
# @version ^0.4.0

@external
def foo() -> uint256:
    return 42
"""
        module_t = _get_module_t(source)
        deploy_ctx, runtime_ctx = generate_ir_for_module(module_t)

        assert deploy_ctx is not None
        assert runtime_ctx is not None


class TestExternalEntryPoints:
    """Test external function entry point generation."""

    def test_entry_point_min_calldatasize(self):
        """Test that entry points have correct min_calldatasize."""
        source = """
# @version ^0.4.0

@external
def foo() -> uint256:
    return 42

@external
def bar(x: uint256) -> uint256:
    return x
"""
        module_t = _get_module_t(source)
        compiler = VenomModuleCompiler(module_t)

        # Get entry points for foo
        for fn_t in module_t.exposed_functions:
            compiler.id_generator.ensure_id(fn_t)
            from vyper.codegen_venom.module import _init_ir_info
            _init_ir_info(fn_t)

            from vyper.venom.context import IRContext
            ir_ctx = IRContext()

            entry_points = compiler._generate_external_entry_points(
                ir_ctx, fn_t, fn_t.ast_def
            )

            if fn_t.name == "foo":
                # foo() - just selector
                assert len(entry_points) == 1
                for ep in entry_points.values():
                    assert ep.min_calldatasize == 4

            if fn_t.name == "bar":
                # bar(uint256) - selector + one word
                assert len(entry_points) == 1
                for ep in entry_points.values():
                    assert ep.min_calldatasize == 4 + 32

    def test_kwargs_create_multiple_entry_points(self):
        """Test that kwargs create multiple entry points."""
        source = """
# @version ^0.4.0

@external
def foo(a: uint256, b: uint256 = 10, c: uint256 = 20) -> uint256:
    return a + b + c
"""
        module_t = _get_module_t(source)
        compiler = VenomModuleCompiler(module_t)

        for fn_t in module_t.exposed_functions:
            compiler.id_generator.ensure_id(fn_t)
            from vyper.codegen_venom.module import _init_ir_info
            _init_ir_info(fn_t)

            from vyper.venom.context import IRContext
            ir_ctx = IRContext()

            entry_points = compiler._generate_external_entry_points(
                ir_ctx, fn_t, fn_t.ast_def
            )

            if fn_t.name == "foo":
                # Should have 3 entry points:
                # foo(uint256)
                # foo(uint256, uint256)
                # foo(uint256, uint256, uint256)
                assert len(entry_points) == 3


class TestIDGenerator:
    """Test ID generation for functions."""

    def test_unique_ids(self):
        """Test that functions get unique IDs."""
        source = """
# @version ^0.4.0

@external
def foo():
    pass

@external
def bar():
    pass

@internal
def _helper():
    pass
"""
        from vyper.codegen_venom.module import IDGenerator

        module_t = _get_module_t(source)
        id_gen = IDGenerator()

        ids = set()
        for fn_t in module_t.exposed_functions:
            id_gen.ensure_id(fn_t)
            assert fn_t._function_id is not None
            ids.add(fn_t._function_id)

        # All IDs should be unique
        assert len(ids) == 2  # foo and bar


class TestNonreentrantExternal:
    """Test nonreentrant handling in external functions."""

    def test_nonreentrant_external(self):
        """Test nonreentrant external function compiles."""
        source = """
# @version ^0.4.0

@external
@nonreentrant
def foo():
    pass
"""
        module_t = _get_module_t(source)
        compiler = VenomModuleCompiler(module_t)
        deploy_ctx, runtime_ctx = compiler.compile()

        assert deploy_ctx is not None
        assert runtime_ctx is not None
