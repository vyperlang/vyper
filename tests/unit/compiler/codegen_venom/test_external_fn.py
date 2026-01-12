"""
Tests for external function codegen and selector dispatch.
"""
import pytest

from vyper.codegen_venom.constants import SELECTOR_BYTES
from vyper.codegen_venom.module import (
    IDGenerator,
    _init_ir_info,
    _generate_external_entry_points,
)
from vyper.compiler.phases import CompilerData


def _get_module_t(source: str):
    """Get module type from source."""
    compiler_data = CompilerData(source)
    return compiler_data.global_ctx


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
        id_generator = IDGenerator()

        # Get entry points for each function
        for fn_t in module_t.exposed_functions:
            id_generator.ensure_id(fn_t)
            _init_ir_info(fn_t)

            entry_points = _generate_external_entry_points(fn_t)

            if fn_t.name == "foo":
                # foo() - just selector
                assert len(entry_points) == 1
                for ep in entry_points.values():
                    assert ep.min_calldatasize == SELECTOR_BYTES

            if fn_t.name == "bar":
                # bar(uint256) - selector + one word
                assert len(entry_points) == 1
                for ep in entry_points.values():
                    assert ep.min_calldatasize == SELECTOR_BYTES + 32

    def test_kwargs_create_multiple_entry_points(self):
        """Test that kwargs create multiple entry points."""
        source = """
# @version ^0.4.0

@external
def foo(a: uint256, b: uint256 = 10, c: uint256 = 20) -> uint256:
    return a + b + c
"""
        module_t = _get_module_t(source)
        id_generator = IDGenerator()

        for fn_t in module_t.exposed_functions:
            id_generator.ensure_id(fn_t)
            _init_ir_info(fn_t)

            entry_points = _generate_external_entry_points(fn_t)

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
        module_t = _get_module_t(source)
        id_gen = IDGenerator()

        ids = set()
        for fn_t in module_t.exposed_functions:
            id_gen.ensure_id(fn_t)
            assert fn_t._function_id is not None
            ids.add(fn_t._function_id)

        # All IDs should be unique
        assert len(ids) == 2  # foo and bar
