"""
Tests for struct and tuple literal construction and assignment.

These tests cover:
- Tuple literal construction (a, b, c)
- Struct literal construction MyStruct(field=val)
- Complex type assignment with temp buffer
- Tuple unpacking a, b = expr
"""
import pytest

from vyper.codegen_venom.context import VenomCodegenContext
from vyper.codegen_venom.stmt import Stmt
from vyper.codegen_venom.expr import Expr
from vyper.compiler.phases import CompilerData
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext


def _get_stmt_context(source: str) -> tuple[VenomCodegenContext, "vy_ast.VyperNode"]:
    """
    Compile source and return (VenomCodegenContext, first statement node).
    """
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
    assert func_def is not None, "No function found in source"

    func_t = func_def._metadata["func_type"]
    codegen_ctx.func_t = func_t  # Set function type for return statements
    for arg in func_t.arguments:
        codegen_ctx.new_variable(arg.name, arg.typ)

    first_stmt = func_def.body[0]

    return codegen_ctx, first_stmt


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
    codegen_ctx.func_t = func_t  # Set function type for return statements
    for arg in func_t.arguments:
        codegen_ctx.new_variable(arg.name, arg.typ)

    return codegen_ctx, func_def.body


class TestTupleLiteral:
    """Test lowering of tuple literal construction."""

    def test_simple_tuple_literal(self):
        source = """
# @version ^0.4.0
@external
def foo() -> (uint256, uint256):
    return (1, 2)
"""
        ctx, stmt = _get_stmt_context(source)
        # The return statement contains a tuple expression
        Stmt(stmt, ctx).lower()

    def test_tuple_with_variables(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> (uint256, uint256):
    return (a, b)
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()

    def test_tuple_with_expressions(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> (uint256, uint256):
    return (a + 1, b * 2)
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()

    def test_three_element_tuple(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256, c: uint256) -> (uint256, uint256, uint256):
    return (a, b, c)
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()

    def test_mixed_type_tuple(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: bool) -> (uint256, bool):
    return (a, b)
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()


class TestStructLiteral:
    """Test lowering of struct literal construction."""

    def test_simple_struct_literal(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

@external
def foo() -> Point:
    return Point(x=1, y=2)
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()

    def test_struct_with_variables(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

@external
def foo(a: uint256, b: uint256) -> Point:
    return Point(x=a, y=b)
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()

    def test_struct_with_expressions(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

@external
def foo(a: uint256, b: uint256) -> Point:
    return Point(x=a + 1, y=b * 2)
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()

    def test_three_field_struct(self):
        source = """
# @version ^0.4.0
struct Vec3:
    x: uint256
    y: uint256
    z: uint256

@external
def foo(a: uint256, b: uint256, c: uint256) -> Vec3:
    return Vec3(x=a, y=b, z=c)
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()

    def test_mixed_type_struct(self):
        source = """
# @version ^0.4.0
struct Info:
    amount: uint256
    active: bool

@external
def foo(a: uint256, b: bool) -> Info:
    return Info(amount=a, active=b)
"""
        ctx, stmt = _get_stmt_context(source)
        Stmt(stmt, ctx).lower()


class TestComplexTypeAssignment:
    """Test assignment of complex (multi-word) types."""

    def test_struct_assignment_local(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

@external
def foo():
    p: Point = Point(x=1, y=2)
    q: Point = Point(x=0, y=0)
    q = p
"""
        ctx, stmts = _get_all_stmts(source)
        for stmt in stmts:
            Stmt(stmt, ctx).lower()

    def test_struct_assignment_storage(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

stored: Point

@external
def foo():
    p: Point = Point(x=1, y=2)
    self.stored = p
"""
        ctx, stmts = _get_all_stmts(source)
        for stmt in stmts:
            Stmt(stmt, ctx).lower()

    # Static array assignment requires List literal support (Task 25)
    # def test_static_array_assignment(self):


class TestTupleUnpacking:
    """Test tuple unpacking assignment.

    Note: Vyper semantic analysis may convert `a, b = 1, 2` into separate
    assignments in some cases. These tests use function returns to ensure
    actual tuple unpacking is tested.
    """

    def test_tuple_unpack_from_internal_fn(self):
        """Test tuple unpacking from internal function return."""
        source = """
# @version ^0.4.0

@internal
def get_pair() -> (uint256, uint256):
    return 1, 2

@external
def foo():
    a: uint256 = 0
    b: uint256 = 0
    a, b = self.get_pair()
"""
        ctx, stmts = _get_all_stmts(source)
        for stmt in stmts:
            Stmt(stmt, ctx).lower()

    def test_tuple_unpack_from_variables(self):
        """Test tuple unpacking from tuple constructed from variables."""
        source = """
# @version ^0.4.0

@internal
def get_swapped(x: uint256, y: uint256) -> (uint256, uint256):
    return y, x

@external
def foo(x: uint256, y: uint256):
    a: uint256 = 0
    b: uint256 = 0
    a, b = self.get_swapped(x, y)
"""
        ctx, stmts = _get_all_stmts(source)
        for stmt in stmts:
            Stmt(stmt, ctx).lower()

    def test_three_element_unpack(self):
        """Test three-element tuple unpacking."""
        source = """
# @version ^0.4.0

@internal
def get_triple() -> (uint256, uint256, uint256):
    return 1, 2, 3

@external
def foo():
    a: uint256 = 0
    b: uint256 = 0
    c: uint256 = 0
    a, b, c = self.get_triple()
"""
        ctx, stmts = _get_all_stmts(source)
        for stmt in stmts:
            Stmt(stmt, ctx).lower()

    def test_mixed_type_unpack(self):
        """Test tuple unpacking with mixed types."""
        source = """
# @version ^0.4.0

@internal
def get_mixed() -> (uint256, bool):
    return 42, True

@external
def foo():
    a: uint256 = 0
    b: bool = False
    a, b = self.get_mixed()
"""
        ctx, stmts = _get_all_stmts(source)
        for stmt in stmts:
            Stmt(stmt, ctx).lower()
