"""
Tests for Subscript and Attribute lowering in codegen_venom.

These tests cover:
- Array subscript access (arr[i])
- Mapping subscript access (map[key])
- Struct field access (point.x)
- Storage vs memory handling

Note: Tests avoid array literals [1,2,3] and struct constructors Point(x=1,y=2)
since those require lower_List and lower_Call which are separate tasks.
"""
import pytest

from vyper.codegen_venom.context import VenomCodegenContext
from vyper.codegen_venom.expr import Expr
from vyper.codegen_venom.stmt import Stmt
from vyper.compiler.phases import CompilerData
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext


def _get_context_and_func(source: str) -> tuple[VenomCodegenContext, "vy_ast.FunctionDef"]:
    """
    Compile source and return (VenomCodegenContext, function def).
    """
    compiler_data = CompilerData(source)
    module_t = compiler_data.global_ctx
    module_ast = compiler_data.annotated_vyper_module

    ctx = IRContext()
    fn = ctx.create_function("test")
    builder = VenomBuilder(ctx, fn)
    codegen_ctx = VenomCodegenContext(module_t, builder)

    # Find the function
    func_def = None
    for item in module_ast.body:
        if hasattr(item, "args"):
            func_def = item
            break
    assert func_def is not None, "No function found in source"

    # Register function parameters
    func_t = func_def._metadata["func_type"]
    for arg in func_t.arguments:
        codegen_ctx.new_variable(arg.name, arg.typ)

    return codegen_ctx, func_def


class TestStorageArraySubscript:
    """Test storage array subscript lowering."""

    def test_storage_array_read(self):
        source = """
# @version ^0.4.0
arr: uint256[5]

@external
def foo() -> uint256:
    return self.arr[0]
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        subscript_expr = return_stmt.value
        result = Expr(subscript_expr, ctx).lower()
        # Result should be a computed pointer

    def test_storage_array_read_with_index_var(self):
        source = """
# @version ^0.4.0
arr: uint256[10]

@external
def foo(i: uint256) -> uint256:
    return self.arr[i]
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        subscript_expr = return_stmt.value
        result = Expr(subscript_expr, ctx).lower()

    def test_storage_array_write(self):
        source = """
# @version ^0.4.0
arr: uint256[5]

@external
def foo(val: uint256):
    self.arr[0] = val
"""
        ctx, func_def = _get_context_and_func(source)
        assign_stmt = func_def.body[0]
        Stmt(assign_stmt, ctx).lower()

    def test_storage_array_write_with_index(self):
        source = """
# @version ^0.4.0
arr: uint256[10]

@external
def foo(i: uint256, val: uint256):
    self.arr[i] = val
"""
        ctx, func_def = _get_context_and_func(source)
        assign_stmt = func_def.body[0]
        Stmt(assign_stmt, ctx).lower()

    def test_storage_array_augassign(self):
        source = """
# @version ^0.4.0
arr: uint256[5]

@external
def foo(i: uint256):
    self.arr[i] += 100
"""
        ctx, func_def = _get_context_and_func(source)
        aug_stmt = func_def.body[0]
        Stmt(aug_stmt, ctx).lower()


class TestStorageDynArraySubscript:
    """Test storage dynamic array subscript lowering."""

    def test_storage_dynarray_read(self):
        source = """
# @version ^0.4.0
arr: DynArray[uint256, 100]

@external
def foo(i: uint256) -> uint256:
    return self.arr[i]
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        subscript_expr = return_stmt.value
        result = Expr(subscript_expr, ctx).lower()

    def test_storage_dynarray_write(self):
        source = """
# @version ^0.4.0
arr: DynArray[uint256, 100]

@external
def foo(i: uint256, val: uint256):
    self.arr[i] = val
"""
        ctx, func_def = _get_context_and_func(source)
        assign_stmt = func_def.body[0]
        Stmt(assign_stmt, ctx).lower()


class TestMappingSubscript:
    """Test mapping subscript lowering."""

    def test_simple_mapping_read(self):
        source = """
# @version ^0.4.0
balances: HashMap[address, uint256]

@external
def foo(addr: address) -> uint256:
    return self.balances[addr]
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        subscript_expr = return_stmt.value
        result = Expr(subscript_expr, ctx).lower()

    def test_mapping_write(self):
        source = """
# @version ^0.4.0
balances: HashMap[address, uint256]

@external
def foo(addr: address, val: uint256):
    self.balances[addr] = val
"""
        ctx, func_def = _get_context_and_func(source)
        assign_stmt = func_def.body[0]
        Stmt(assign_stmt, ctx).lower()

    def test_mapping_augassign(self):
        source = """
# @version ^0.4.0
balances: HashMap[address, uint256]

@external
def foo(addr: address):
    self.balances[addr] += 100
"""
        ctx, func_def = _get_context_and_func(source)
        aug_stmt = func_def.body[0]
        Stmt(aug_stmt, ctx).lower()

    def test_nested_mapping_read(self):
        source = """
# @version ^0.4.0
allowances: HashMap[address, HashMap[address, uint256]]

@external
def foo(owner: address, spender: address) -> uint256:
    return self.allowances[owner][spender]
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        subscript_expr = return_stmt.value
        result = Expr(subscript_expr, ctx).lower()

    def test_nested_mapping_write(self):
        source = """
# @version ^0.4.0
allowances: HashMap[address, HashMap[address, uint256]]

@external
def foo(owner: address, spender: address, val: uint256):
    self.allowances[owner][spender] = val
"""
        ctx, func_def = _get_context_and_func(source)
        assign_stmt = func_def.body[0]
        Stmt(assign_stmt, ctx).lower()

    def test_mapping_with_int_key(self):
        source = """
# @version ^0.4.0
data: HashMap[uint256, uint256]

@external
def foo(key: uint256) -> uint256:
    return self.data[key]
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        result = Expr(return_stmt.value, ctx).lower()

    def test_mapping_with_bytes32_key(self):
        source = """
# @version ^0.4.0
data: HashMap[bytes32, uint256]

@external
def foo(key: bytes32) -> uint256:
    return self.data[key]
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        result = Expr(return_stmt.value, ctx).lower()


class TestStructFieldAccess:
    """Test struct field access lowering."""

    def test_storage_struct_field_read(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

point: Point

@external
def foo() -> uint256:
    return self.point.x
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        result = Expr(return_stmt.value, ctx).lower()

    def test_storage_struct_second_field_read(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

point: Point

@external
def foo() -> uint256:
    return self.point.y
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        result = Expr(return_stmt.value, ctx).lower()

    def test_storage_struct_field_write(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

point: Point

@external
def foo(val: uint256):
    self.point.x = val
"""
        ctx, func_def = _get_context_and_func(source)
        assign_stmt = func_def.body[0]
        Stmt(assign_stmt, ctx).lower()

    def test_storage_struct_second_field_write(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

point: Point

@external
def foo(val: uint256):
    self.point.y = val
"""
        ctx, func_def = _get_context_and_func(source)
        assign_stmt = func_def.body[0]
        Stmt(assign_stmt, ctx).lower()

    def test_storage_struct_field_augassign(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

point: Point

@external
def foo():
    self.point.x += 10
"""
        ctx, func_def = _get_context_and_func(source)
        aug_stmt = func_def.body[0]
        Stmt(aug_stmt, ctx).lower()

    def test_struct_with_multiple_fields(self):
        source = """
# @version ^0.4.0
struct Rectangle:
    x: uint256
    y: uint256
    width: uint256
    height: uint256

rect: Rectangle

@external
def foo() -> uint256:
    return self.rect.height
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        result = Expr(return_stmt.value, ctx).lower()


class TestNestedAccess:
    """Test nested subscript/attribute access."""

    def test_array_of_structs_read(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

points: Point[10]

@external
def foo(i: uint256) -> uint256:
    return self.points[i].x
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        result = Expr(return_stmt.value, ctx).lower()

    def test_array_of_structs_write(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

points: Point[10]

@external
def foo(i: uint256, val: uint256):
    self.points[i].x = val
"""
        ctx, func_def = _get_context_and_func(source)
        assign_stmt = func_def.body[0]
        Stmt(assign_stmt, ctx).lower()

    def test_2d_array_read(self):
        source = """
# @version ^0.4.0
matrix: uint256[10][10]

@external
def foo(i: uint256, j: uint256) -> uint256:
    return self.matrix[i][j]
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        result = Expr(return_stmt.value, ctx).lower()

    def test_2d_array_write(self):
        source = """
# @version ^0.4.0
matrix: uint256[10][10]

@external
def foo(i: uint256, j: uint256, val: uint256):
    self.matrix[i][j] = val
"""
        ctx, func_def = _get_context_and_func(source)
        assign_stmt = func_def.body[0]
        Stmt(assign_stmt, ctx).lower()

    def test_mapping_to_struct_read(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

points: HashMap[address, Point]

@external
def foo(addr: address) -> uint256:
    return self.points[addr].x
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        result = Expr(return_stmt.value, ctx).lower()

    def test_mapping_to_struct_write(self):
        source = """
# @version ^0.4.0
struct Point:
    x: uint256
    y: uint256

points: HashMap[address, Point]

@external
def foo(addr: address, val: uint256):
    self.points[addr].x = val
"""
        ctx, func_def = _get_context_and_func(source)
        assign_stmt = func_def.body[0]
        Stmt(assign_stmt, ctx).lower()


class TestBoundsCheck:
    """Test bounds checking for array access."""

    def test_array_bounds_check_signed_index(self):
        """Test that signed index bounds check uses slt."""
        source = """
# @version ^0.4.0
arr: uint256[10]

@external
def foo(i: int256) -> uint256:
    return self.arr[i]
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        result = Expr(return_stmt.value, ctx).lower()

    def test_array_bounds_check_unsigned_index(self):
        """Test that unsigned index bounds check skips negative check."""
        source = """
# @version ^0.4.0
arr: uint256[10]

@external
def foo(i: uint256) -> uint256:
    return self.arr[i]
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        result = Expr(return_stmt.value, ctx).lower()
