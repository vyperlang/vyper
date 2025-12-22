"""
Tests for DynArray operations lowering in codegen_venom.

These tests cover:
- DynArray.append() for memory and storage arrays
- DynArray.pop() for memory and storage arrays
- List literal lowering: [1, 2, 3]
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

    # Register function parameters and set func_t
    func_t = func_def._metadata["func_type"]
    codegen_ctx.func_t = func_t  # Required for return statements
    for arg in func_t.arguments:
        codegen_ctx.new_variable(arg.name, arg.typ)

    return codegen_ctx, func_def


class TestStorageDynArrayAppend:
    """Test storage DynArray.append() lowering."""

    def test_storage_dynarray_append_simple(self):
        source = """
# @version ^0.4.0
arr: DynArray[uint256, 100]

@external
def foo(val: uint256):
    self.arr.append(val)
"""
        ctx, func_def = _get_context_and_func(source)
        append_stmt = func_def.body[0]
        Stmt(append_stmt, ctx).lower()

    def test_storage_dynarray_append_literal(self):
        source = """
# @version ^0.4.0
arr: DynArray[uint256, 100]

@external
def foo():
    self.arr.append(42)
"""
        ctx, func_def = _get_context_and_func(source)
        append_stmt = func_def.body[0]
        Stmt(append_stmt, ctx).lower()

    def test_storage_dynarray_append_multiple(self):
        source = """
# @version ^0.4.0
arr: DynArray[uint256, 100]

@external
def foo():
    self.arr.append(1)
    self.arr.append(2)
    self.arr.append(3)
"""
        ctx, func_def = _get_context_and_func(source)
        for stmt in func_def.body:
            Stmt(stmt, ctx).lower()


class TestStorageDynArrayPop:
    """Test storage DynArray.pop() lowering."""

    def test_storage_dynarray_pop_stmt(self):
        """Pop as statement (discard value)."""
        source = """
# @version ^0.4.0
arr: DynArray[uint256, 100]

@external
def foo():
    self.arr.pop()
"""
        ctx, func_def = _get_context_and_func(source)
        pop_stmt = func_def.body[0]
        Stmt(pop_stmt, ctx).lower()

    def test_storage_dynarray_pop_expr(self):
        """Pop as expression (use return value)."""
        source = """
# @version ^0.4.0
arr: DynArray[uint256, 100]

@external
def foo() -> uint256:
    return self.arr.pop()
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_storage_dynarray_pop_assign(self):
        """Pop and assign to variable."""
        source = """
# @version ^0.4.0
arr: DynArray[uint256, 100]

@external
def foo() -> uint256:
    x: uint256 = self.arr.pop()
    return x
"""
        ctx, func_def = _get_context_and_func(source)
        for stmt in func_def.body:
            Stmt(stmt, ctx).lower()


class TestMemoryDynArrayAppend:
    """Test memory DynArray.append() lowering."""

    def test_memory_dynarray_append_simple(self):
        source = """
# @version ^0.4.0

@external
def foo(val: uint256):
    arr: DynArray[uint256, 100] = []
    arr.append(val)
"""
        ctx, func_def = _get_context_and_func(source)
        for stmt in func_def.body:
            Stmt(stmt, ctx).lower()

    def test_memory_dynarray_append_multiple(self):
        source = """
# @version ^0.4.0

@external
def foo():
    arr: DynArray[uint256, 100] = []
    arr.append(1)
    arr.append(2)
    arr.append(3)
"""
        ctx, func_def = _get_context_and_func(source)
        for stmt in func_def.body:
            Stmt(stmt, ctx).lower()


class TestMemoryDynArrayPop:
    """Test memory DynArray.pop() lowering."""

    def test_memory_dynarray_pop_stmt(self):
        """Pop as statement (discard value)."""
        source = """
# @version ^0.4.0

@external
def foo():
    arr: DynArray[uint256, 100] = [1, 2, 3]
    arr.pop()
"""
        ctx, func_def = _get_context_and_func(source)
        for stmt in func_def.body:
            Stmt(stmt, ctx).lower()

    def test_memory_dynarray_pop_expr(self):
        """Pop as expression (use return value)."""
        source = """
# @version ^0.4.0

@external
def foo() -> uint256:
    arr: DynArray[uint256, 100] = [1, 2, 3]
    return arr.pop()
"""
        ctx, func_def = _get_context_and_func(source)
        for stmt in func_def.body:
            Stmt(stmt, ctx).lower()


class TestListLiteral:
    """Test list literal lowering: [a, b, c]."""

    def test_list_literal_simple(self):
        source = """
# @version ^0.4.0

@external
def foo() -> uint256:
    arr: DynArray[uint256, 10] = [1, 2, 3]
    return arr[0]
"""
        ctx, func_def = _get_context_and_func(source)
        for stmt in func_def.body:
            Stmt(stmt, ctx).lower()

    def test_list_literal_empty(self):
        source = """
# @version ^0.4.0

@external
def foo() -> uint256:
    arr: DynArray[uint256, 10] = []
    return 0
"""
        ctx, func_def = _get_context_and_func(source)
        for stmt in func_def.body:
            Stmt(stmt, ctx).lower()

    def test_list_literal_with_vars(self):
        source = """
# @version ^0.4.0

@external
def foo(x: uint256, y: uint256) -> uint256:
    arr: DynArray[uint256, 10] = [x, y, x + y]
    return arr[2]
"""
        ctx, func_def = _get_context_and_func(source)
        for stmt in func_def.body:
            Stmt(stmt, ctx).lower()

    def test_list_literal_address(self):
        source = """
# @version ^0.4.0

@external
def foo(addr: address) -> address:
    addrs: DynArray[address, 10] = [addr, msg.sender]
    return addrs[0]
"""
        ctx, func_def = _get_context_and_func(source)
        for stmt in func_def.body:
            Stmt(stmt, ctx).lower()


class TestDynArrayComplexTypes:
    """Test DynArray operations with complex element types."""

    def test_dynarray_struct_append(self):
        source = """
# @version ^0.4.0

struct Point:
    x: uint256
    y: uint256

arr: DynArray[Point, 100]

@external
def foo(x: uint256, y: uint256):
    self.arr.append(Point(x=x, y=y))
"""
        ctx, func_def = _get_context_and_func(source)
        for stmt in func_def.body:
            Stmt(stmt, ctx).lower()

    def test_dynarray_struct_pop(self):
        source = """
# @version ^0.4.0

struct Point:
    x: uint256
    y: uint256

arr: DynArray[Point, 100]

@external
def foo() -> uint256:
    p: Point = self.arr.pop()
    return p.x
"""
        ctx, func_def = _get_context_and_func(source)
        for stmt in func_def.body:
            Stmt(stmt, ctx).lower()
