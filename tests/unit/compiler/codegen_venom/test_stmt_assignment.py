"""
Tests for Stmt assignment lowering in codegen_venom.

Tests that variable registration works correctly.
"""
import pytest

from vyper.codegen_venom.context import VenomCodegenContext
from vyper.codegen_venom.stmt import Stmt
from vyper.compiler.phases import CompilerData
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext


def _get_stmt_context(source: str) -> tuple[VenomCodegenContext, "vy_ast.VyperNode"]:
    """
    Compile source and return (VenomCodegenContext, first statement node).

    The source should be a function with statements to test.
    """
    compiler_data = CompilerData(source)
    # Access global_ctx to ensure storage layout is computed
    # This populates varinfo.position for state variables
    module_t = compiler_data.global_ctx
    module_ast = compiler_data.annotated_vyper_module

    ctx = IRContext()
    fn = ctx.create_function("test")
    builder = VenomBuilder(ctx, fn)
    codegen_ctx = VenomCodegenContext(module_t, builder)

    # Get first function definition
    func_def = None
    for item in module_ast.body:
        if hasattr(item, "args"):
            func_def = item
            break
    assert func_def is not None, "No function found in source"

    # Register function parameters in codegen context
    func_t = func_def._metadata["func_type"]
    for arg in func_t.arguments:
        codegen_ctx.new_variable(arg.name, arg.typ)

    first_stmt = func_def.body[0]

    return codegen_ctx, first_stmt


def _get_all_stmts(source: str) -> tuple[VenomCodegenContext, list]:
    """Get context and all statements from a function."""
    compiler_data = CompilerData(source)
    # Access global_ctx to ensure storage layout is computed
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


class TestAnnAssign:
    """Test lowering of annotated assignment (variable declaration)."""

    def test_simple_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: uint256 = 5
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()

        # Variable should be registered in context
        assert "x" in ctx.variables


class TestAssign:
    """Test lowering of regular assignment."""

    def test_reassign_local(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256):
    y: uint256 = 0
    y = x
"""
        ctx, stmts = _get_all_stmts(source)

        # Execute first statement (declaration)
        Stmt(stmts[0], ctx).lower()
        assert "y" in ctx.variables

        # Execute second statement (reassignment)
        Stmt(stmts[1], ctx).lower()


class TestStateVariableAssignment:
    """Test assignment to state variables."""

    def test_storage_assign(self):
        source = """
# @version ^0.4.0
x: uint256

@external
def foo(val: uint256):
    self.x = val
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()
