"""
Tests for String/Bytes operations in codegen_venom.

These tests cover:
- len() for bytes/string/DynArray in memory and storage
- concat(a, b, ...) for bytes/string (memory and storage sources)
- slice(b, start, length) for standard, adhoc, and storage sources
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


class TestLenMemory:
    """Test len() for memory-based types."""

    def test_len_memory_bytes(self):
        """len() on memory bytes."""
        source = """
# @version ^0.4.0

@external
def foo(b: Bytes[100]) -> uint256:
    return len(b)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_len_memory_string(self):
        """len() on memory string."""
        source = """
# @version ^0.4.0

@external
def foo(s: String[100]) -> uint256:
    return len(s)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_len_memory_dynarray(self):
        """len() on memory DynArray."""
        source = """
# @version ^0.4.0

@external
def foo() -> uint256:
    arr: DynArray[uint256, 100] = [1, 2, 3]
    return len(arr)
"""
        ctx, func_def = _get_context_and_func(source)
        for stmt in func_def.body:
            Stmt(stmt, ctx).lower()

    def test_len_msg_data(self):
        """len(msg.data) -> calldatasize."""
        source = """
# @version ^0.4.0

@external
def foo() -> uint256:
    return len(msg.data)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()


class TestLenStorage:
    """Test len() for storage-based types."""

    def test_len_storage_bytes(self):
        """len() on storage bytes."""
        source = """
# @version ^0.4.0

my_bytes: Bytes[100]

@external
def foo() -> uint256:
    return len(self.my_bytes)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_len_storage_string(self):
        """len() on storage string."""
        source = """
# @version ^0.4.0

my_string: String[100]

@external
def foo() -> uint256:
    return len(self.my_string)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_len_storage_dynarray(self):
        """len() on storage DynArray."""
        source = """
# @version ^0.4.0

arr: DynArray[uint256, 100]

@external
def foo() -> uint256:
    return len(self.arr)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()


class TestConcatMemory:
    """Test concat() with memory-based arguments."""

    def test_concat_two_bytes(self):
        """concat(bytes, bytes)."""
        source = """
# @version ^0.4.0

@external
def foo(a: Bytes[50], b: Bytes[50]) -> Bytes[100]:
    return concat(a, b)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_concat_two_strings(self):
        """concat(string, string)."""
        source = """
# @version ^0.4.0

@external
def foo(a: String[50], b: String[50]) -> String[100]:
    return concat(a, b)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_concat_bytesM_and_bytes(self):
        """concat(bytes4, bytes) - bytesM contributes fixed bytes."""
        source = """
# @version ^0.4.0

@external
def foo(b: Bytes[50]) -> Bytes[54]:
    return concat(0x12345678, b)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_concat_three_args(self):
        """concat(bytes, bytes, bytes)."""
        source = """
# @version ^0.4.0

@external
def foo(a: Bytes[30], b: Bytes[30], c: Bytes[30]) -> Bytes[90]:
    return concat(a, b, c)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()


class TestConcatStorage:
    """Test concat() with storage-based arguments."""

    def test_concat_storage_bytes(self):
        """concat() with storage bytes arg."""
        source = """
# @version ^0.4.0

my_bytes: Bytes[50]

@external
def foo(b: Bytes[50]) -> Bytes[100]:
    return concat(self.my_bytes, b)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_concat_both_storage(self):
        """concat() with both args from storage."""
        source = """
# @version ^0.4.0

a: Bytes[50]
b: Bytes[50]

@external
def foo() -> Bytes[100]:
    return concat(self.a, self.b)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()


class TestSliceStandard:
    """Test slice() for standard memory/bytes sources."""

    def test_slice_bytes_literal_length(self):
        """slice(bytes, start, length) with literal length."""
        source = """
# @version ^0.4.0

@external
def foo(b: Bytes[100], start: uint256) -> Bytes[10]:
    return slice(b, start, 10)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_slice_string(self):
        """slice(string, start, length)."""
        source = """
# @version ^0.4.0

@external
def foo(s: String[100], start: uint256) -> String[20]:
    return slice(s, start, 20)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_slice_from_start(self):
        """slice(bytes, 0, length)."""
        source = """
# @version ^0.4.0

@external
def foo(b: Bytes[100]) -> Bytes[5]:
    return slice(b, 0, 5)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_slice_bytes32(self):
        """slice(bytes32, start, length)."""
        source = """
# @version ^0.4.0

@external
def foo(b: bytes32) -> Bytes[10]:
    return slice(b, 0, 10)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()


class TestSliceAdhoc:
    """Test slice() for adhoc sources (msg.data, self.code, addr.code)."""

    def test_slice_msg_data(self):
        """slice(msg.data, start, length)."""
        source = """
# @version ^0.4.0

@external
def foo() -> Bytes[10]:
    return slice(msg.data, 0, 10)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_slice_self_code(self):
        """slice(self.code, start, length)."""
        source = """
# @version ^0.4.0

@external
def foo() -> Bytes[10]:
    return slice(self.code, 0, 10)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_slice_addr_code(self):
        """slice(<addr>.code, start, length)."""
        source = """
# @version ^0.4.0

@external
def foo(addr: address) -> Bytes[10]:
    return slice(addr.code, 0, 10)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_slice_msg_data_variable_start(self):
        """slice(msg.data, variable_start, length)."""
        source = """
# @version ^0.4.0

@external
def foo(start: uint256) -> Bytes[10]:
    return slice(msg.data, start, 10)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()


class TestSliceStorage:
    """Test slice() for storage-based sources."""

    def test_slice_storage_bytes(self):
        """slice(storage_bytes, start, length)."""
        source = """
# @version ^0.4.0

my_bytes: Bytes[100]

@external
def foo(start: uint256) -> Bytes[10]:
    return slice(self.my_bytes, start, 10)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_slice_storage_string(self):
        """slice(storage_string, start, length)."""
        source = """
# @version ^0.4.0

my_string: String[100]

@external
def foo(start: uint256) -> String[10]:
    return slice(self.my_string, start, 10)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_slice_storage_from_start(self):
        """slice(storage_bytes, 0, length)."""
        source = """
# @version ^0.4.0

my_bytes: Bytes[100]

@external
def foo() -> Bytes[20]:
    return slice(self.my_bytes, 0, 20)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()


class TestExtract32:
    """Test extract32() builtin."""

    def test_extract32_from_bytes(self):
        """extract32(bytes, start)."""
        source = """
# @version ^0.4.0

@external
def foo(b: Bytes[100]) -> bytes32:
    return extract32(b, 0)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_extract32_with_variable_start(self):
        """extract32(bytes, variable_start)."""
        source = """
# @version ^0.4.0

@external
def foo(b: Bytes[100], start: uint256) -> bytes32:
    return extract32(b, start)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_extract32_to_int(self):
        """extract32(bytes, start, output_type=int256)."""
        source = """
# @version ^0.4.0

@external
def foo(b: Bytes[100]) -> int256:
    return extract32(b, 0, output_type=int256)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()

    def test_extract32_to_address(self):
        """extract32(bytes, start, output_type=address)."""
        source = """
# @version ^0.4.0

@external
def foo(b: Bytes[100]) -> address:
    return extract32(b, 0, output_type=address)
"""
        ctx, func_def = _get_context_and_func(source)
        return_stmt = func_def.body[0]
        Stmt(return_stmt, ctx).lower()
