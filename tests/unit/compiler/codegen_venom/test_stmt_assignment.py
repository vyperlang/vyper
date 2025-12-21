"""
Tests for Stmt assignment lowering in codegen_venom.

These tests cover lower_AnnAssign, lower_Assign, and lower_AugAssign for:
- Local variable declaration and assignment
- State variable assignment (storage)
- Augmented assignment operators
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

    def test_simple_bool(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: bool = True
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()

        assert "x" in ctx.variables

    def test_simple_address(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: address = 0x0000000000000000000000000000000000000001
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()

        assert "x" in ctx.variables

    def test_bytes32(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: bytes32 = 0x0000000000000000000000000000000000000000000000000000000000000001
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()

        assert "x" in ctx.variables

    def test_init_from_param(self):
        source = """
# @version ^0.4.0
@external
def foo(y: uint256):
    x: uint256 = y
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()

        assert "x" in ctx.variables

    def test_init_from_expression(self):
        source = """
# @version ^0.4.0
@external
def foo(y: uint256):
    x: uint256 = y + 1
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()

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

    def test_assign_from_expression(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256):
    y: uint256 = 0
    y = x + 1
"""
        ctx, stmts = _get_all_stmts(source)

        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()


class TestAugAssign:
    """Test lowering of augmented assignment."""

    def test_add_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: uint256 = 5
    x += 3
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()

    def test_sub_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: uint256 = 5
    x -= 3
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()

    def test_mul_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: uint256 = 5
    x *= 3
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()

    def test_floordiv_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: uint256 = 10
    x //= 3
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()

    def test_mod_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: uint256 = 10
    x %= 3
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()

    def test_pow_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: uint256 = 2
    x **= 3
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()

    def test_bitand_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: uint256 = 255
    x &= 15
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()

    def test_bitor_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: uint256 = 240
    x |= 15
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()

    def test_bitxor_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: uint256 = 255
    x ^= 15
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()

    def test_lshift_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: uint256 = 1
    x <<= 4
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()

    def test_rshift_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: uint256 = 256
    x >>= 4
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()


class TestSignedAugAssign:
    """Test augmented assignment with signed types."""

    def test_signed_add_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: int256 = -5
    x += 3
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()

    def test_signed_sub_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: int256 = 5
    x -= 10
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()

    def test_signed_mul_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: int256 = -5
    x *= 3
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
        Stmt(stmts[1], ctx).lower()

    def test_signed_rshift_assign(self):
        source = """
# @version ^0.4.0
@external
def foo():
    x: int256 = -256
    x >>= 4
"""
        ctx, stmts = _get_all_stmts(source)
        Stmt(stmts[0], ctx).lower()
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

    def test_storage_augassign(self):
        source = """
# @version ^0.4.0
x: uint256

@external
def foo(val: uint256):
    self.x += val
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()
