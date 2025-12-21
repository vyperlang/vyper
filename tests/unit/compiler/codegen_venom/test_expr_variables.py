"""
Tests for Expr variable/name lowering in codegen_venom.

These tests cover lower_Name and lower_Attribute for:
- Local variables
- self keyword
- Environment variables (msg.sender, block.timestamp, etc.)
- Address properties (.balance, .codesize, etc.)
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

    return_stmt = func_def.body[0]
    expr_node = return_stmt.value

    return codegen_ctx, expr_node


class TestLocalVariables:
    """Test lowering of local variable references."""

    def test_simple_param(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256) -> uint256:
    return x
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_multiple_params(self):
        """Variables are looked up correctly when multiple exist."""
        source = """
# @version ^0.4.0
@external
def foo(a: uint256, b: uint256) -> uint256:
    return b
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)


class TestSelfKeyword:
    """Test lowering of 'self' keyword."""

    def test_self_returns_address(self):
        source = """
# @version ^0.4.0
@external
def foo() -> address:
    return self
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)


class TestMsgAttributes:
    """Test lowering of msg.* environment variables."""

    def test_msg_sender(self):
        source = """
# @version ^0.4.0
@external
def foo() -> address:
    return msg.sender
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_msg_value(self):
        source = """
# @version ^0.4.0
@external
@payable
def foo() -> uint256:
    return msg.value
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_msg_gas(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return msg.gas
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)


class TestBlockAttributes:
    """Test lowering of block.* environment variables."""

    def test_block_timestamp(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return block.timestamp
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_block_number(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return block.number
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_block_coinbase(self):
        source = """
# @version ^0.4.0
@external
def foo() -> address:
    return block.coinbase
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_block_gaslimit(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return block.gaslimit
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_block_basefee(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return block.basefee
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_block_prevhash(self):
        source = """
# @version ^0.4.0
@external
def foo() -> bytes32:
    return block.prevhash
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)


class TestTxAttributes:
    """Test lowering of tx.* environment variables."""

    def test_tx_origin(self):
        source = """
# @version ^0.4.0
@external
def foo() -> address:
    return tx.origin
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_tx_gasprice(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return tx.gasprice
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)


class TestChainAttributes:
    """Test lowering of chain.* environment variables."""

    def test_chain_id(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return chain.id
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)


class TestAddressProperties:
    """Test lowering of address property access."""

    def test_balance(self):
        source = """
# @version ^0.4.0
@external
def foo(addr: address) -> uint256:
    return addr.balance
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_self_balance(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return self.balance
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_codesize(self):
        source = """
# @version ^0.4.0
@external
def foo(addr: address) -> uint256:
    return addr.codesize
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_self_codesize(self):
        source = """
# @version ^0.4.0
@external
def foo() -> uint256:
    return self.codesize
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_codehash(self):
        source = """
# @version ^0.4.0
@external
def foo(addr: address) -> bytes32:
    return addr.codehash
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)

    def test_is_contract(self):
        source = """
# @version ^0.4.0
@external
def foo(addr: address) -> bool:
    return addr.is_contract
"""
        ctx, node = _get_expr_context(source)
        result = Expr(node, ctx).lower()

        assert isinstance(result, IRVariable)
