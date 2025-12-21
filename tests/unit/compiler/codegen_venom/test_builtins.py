"""
Tests for built-in function lowering in codegen_venom.
"""
import pytest

from vyper.codegen_venom.context import VenomCodegenContext
from vyper.codegen_venom.expr import Expr
from vyper.compiler.phases import CompilerData
from vyper.venom.basicblock import IRLiteral, IRVariable
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext


def _get_expr_context(source: str) -> tuple[VenomCodegenContext, "vy_ast.VyperNode"]:
    """
    Compile source and return (VenomCodegenContext, expression_node).

    The source should be a function with a single return statement.
    Returns the expression node from that return.
    """
    compiler_data = CompilerData(source)
    module_ast = compiler_data.annotated_vyper_module
    module_t = module_ast._metadata["type"]

    ctx = IRContext()
    fn = ctx.create_function("test")
    builder = VenomBuilder(ctx, fn)
    codegen_ctx = VenomCodegenContext(module_t, builder)

    # Get first function definition
    func_def = module_ast.body[0]

    # Register function parameters in codegen context
    func_t = func_def._metadata["func_type"]
    for arg in func_t.arguments:
        codegen_ctx.new_variable(arg.name, arg.typ)

    return_stmt = func_def.body[0]
    expr_node = return_stmt.value

    return codegen_ctx, expr_node


class TestLen:
    def test_len_dynarray(self):
        source = """
# @version ^0.4.0
@external
def foo(arr: DynArray[uint256, 10]) -> uint256:
    return len(arr)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_len_bytes(self):
        source = """
# @version ^0.4.0
@external
def foo(b: Bytes[100]) -> uint256:
    return len(b)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_len_string(self):
        source = """
# @version ^0.4.0
@external
def foo(s: String[100]) -> uint256:
    return len(s)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)


class TestEmpty:
    def test_empty_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return empty(uint256)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRLiteral)
        assert result.value == 0

    def test_empty_address(self):
        source = """
# @version ^0.4.0
@external
def foo() -> address:
    return empty(address)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRLiteral)
        assert result.value == 0


class TestMinMax:
    def test_min_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return min(a, b)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_max_uint256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return max(a, b)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_min_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: int256, b: int256) -> int256:
    return min(a, b)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_max_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(a: int256, b: int256) -> int256:
    return max(a, b)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)


class TestAbs:
    def test_abs_int256(self):
        source = """
# @version ^0.4.0
@external
def foo(x: int256) -> int256:
    return abs(x)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)


class TestUnsafeMath:
    def test_unsafe_add(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return unsafe_add(a, b)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_unsafe_sub(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return unsafe_sub(a, b)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_unsafe_mul(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return unsafe_mul(a, b)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_unsafe_div(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return unsafe_div(a, b)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_unsafe_div_signed(self):
        source = """
# @version ^0.4.0
@external
def foo(a: int256, b: int256) -> int256:
    return unsafe_div(a, b)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_pow_mod256(self):
        source = """
# @version ^0.4.0
@external
def foo(base: uint256, exp: uint256) -> uint256:
    return pow_mod256(base, exp)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_uint256_addmod(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256, c: uint256) -> uint256:
    return uint256_addmod(a, b, c)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_uint256_mulmod(self):
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256, c: uint256) -> uint256:
    return uint256_mulmod(a, b, c)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)


class TestHashing:
    def test_keccak256_bytes(self):
        source = """
# @version ^0.4.0
@external
def foo(data: Bytes[100]) -> bytes32:
    return keccak256(data)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_keccak256_bytes32(self):
        source = """
# @version ^0.4.0
@external
def foo(data: bytes32) -> bytes32:
    return keccak256(data)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_keccak256_string(self):
        source = """
# @version ^0.4.0
@external
def foo(data: String[100]) -> bytes32:
    return keccak256(data)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_sha256_bytes(self):
        source = """
# @version ^0.4.0
@external
def foo(data: Bytes[100]) -> bytes32:
    return sha256(data)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)

    def test_sha256_bytes32(self):
        source = """
# @version ^0.4.0
@external
def foo(data: bytes32) -> bytes32:
    return sha256(data)
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()
        assert isinstance(result, IRVariable)
