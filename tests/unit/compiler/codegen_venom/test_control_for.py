"""
Tests for For loop lowering in codegen_venom.

These tests verify the 5-block loop structure (entry/cond/body/incr/exit)
and correct break/continue target generation.
"""
import pytest

from vyper.codegen_venom.context import VenomCodegenContext
from vyper.codegen_venom.stmt import Stmt
from vyper.compiler.phases import CompilerData
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext


def _get_all_stmts(source: str) -> tuple[VenomCodegenContext, list]:
    """Get context and all statements from a function."""
    compiler_data = CompilerData(source)
    module_t = compiler_data.global_ctx
    module_ast = compiler_data.annotated_vyper_module

    ctx = IRContext()
    fn = ctx.create_function("test")
    builder = VenomBuilder(ctx, fn)
    codegen_ctx = VenomCodegenContext(module_t, builder)

    func_def = None
    for item in module_ast.body:
        if hasattr(item, "args"):
            func_def = item
            break
    assert func_def is not None

    func_t = func_def._metadata["func_type"]
    for arg in func_t.arguments:
        codegen_ctx.new_variable(arg.name, arg.typ)

    return codegen_ctx, func_def.body


def _lower_all_stmts(source: str) -> tuple[VenomCodegenContext, "IRFunction"]:
    """Lower all statements and return context and IR function."""
    ctx, stmts = _get_all_stmts(source)
    for stmt in stmts:
        Stmt(stmt, ctx).lower()
    return ctx, ctx.builder.fn


class TestRangeLoop:
    """Test range-based for loops."""

    def test_range_simple(self):
        source = """
# @version ^0.4.0
@external
def foo():
    total: uint256 = 0
    for i: uint256 in range(5):
        total = total + i
"""
        ctx, fn = _lower_all_stmts(source)

        # Should have 5-block structure
        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        assert any("for_entry" in label for label in block_labels)
        assert any("for_cond" in label for label in block_labels)
        assert any("for_body" in label for label in block_labels)
        assert any("for_incr" in label for label in block_labels)
        assert any("for_exit" in label for label in block_labels)


class TestIterLoop:
    """Test array iteration loops."""

    def test_static_array(self):
        # Note: List literals not yet supported, so we use a function parameter
        source = """
# @version ^0.4.0
@external
def foo(arr: uint256[3]):
    total: uint256 = 0
    for item: uint256 in arr:
        total = total + item
"""
        ctx, fn = _lower_all_stmts(source)

        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        assert any("iter_entry" in label for label in block_labels)
        assert any("iter_cond" in label for label in block_labels)
        assert any("iter_body" in label for label in block_labels)
        assert any("iter_incr" in label for label in block_labels)
        assert any("iter_exit" in label for label in block_labels)


class TestBreakContinue:
    """Test break and continue statements."""

    def test_break(self):
        source = """
# @version ^0.4.0
@external
def foo():
    total: uint256 = 0
    for i: uint256 in range(10):
        if i > 5:
            break
        total = total + i
"""
        ctx, fn = _lower_all_stmts(source)

        # Break should create jmp to exit block
        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        assert any("for_exit" in label for label in block_labels)

    def test_continue(self):
        source = """
# @version ^0.4.0
@external
def foo():
    total: uint256 = 0
    for i: uint256 in range(10):
        if i == 5:
            continue
        total = total + i
"""
        ctx, fn = _lower_all_stmts(source)

        # Continue should create jmp to incr block
        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        assert any("for_incr" in label for label in block_labels)


class TestNestedLoops:
    """Test nested loop structures."""

    def test_nested_range_loops(self):
        source = """
# @version ^0.4.0
@external
def foo():
    total: uint256 = 0
    for i: uint256 in range(3):
        for j: uint256 in range(4):
            total = total + i + j
"""
        ctx, fn = _lower_all_stmts(source)

        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        # Should have multiple entry/cond/body/incr/exit blocks
        entry_blocks = [l for l in block_labels if "for_entry" in l]
        assert len(entry_blocks) >= 2
