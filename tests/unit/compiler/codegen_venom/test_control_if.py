"""
Tests for If/Else control flow lowering in codegen_venom.

These tests verify the block structure (then/else/if_exit, ternary_then/ternary_else/ternary_exit).
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


class TestIfSimple:
    """Test simple if statement."""

    def test_if_simple(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256):
    y: uint256 = 0
    if x > 0:
        y = 1
"""
        ctx, fn = _lower_all_stmts(source)

        # Should have blocks: entry, then, else (empty), if_exit
        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        assert any("then" in label for label in block_labels)
        assert any("else" in label for label in block_labels)
        assert any("if_exit" in label for label in block_labels)


class TestIfElifElse:
    """Test if/elif/else chains."""

    def test_if_elif_else(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256):
    y: uint256 = 0
    if x > 10:
        y = 3
    elif x > 5:
        y = 2
    else:
        y = 1
"""
        ctx, fn = _lower_all_stmts(source)

        # Should have multiple then/else blocks due to elif
        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        then_blocks = [l for l in block_labels if "then" in l]
        # Should have at least 2 then blocks (one for if, one for elif)
        assert len(then_blocks) >= 2


class TestIfExp:
    """Test ternary expression (IfExp)."""

    def test_ifexp_simple(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256):
    y: uint256 = 1 if x > 0 else 0
"""
        ctx, fn = _lower_all_stmts(source)

        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        assert any("ternary_then" in label for label in block_labels)
        assert any("ternary_else" in label for label in block_labels)
        assert any("ternary_exit" in label for label in block_labels)
        assert "y" in ctx.variables
