"""
Tests for assert/raise statement lowering in codegen_venom.

These tests cover lower_Assert and lower_Raise in stmt.py:
- Simple assert (no message)
- Assert with UNREACHABLE
- Assert with reason string
- Bare raise
- Raise UNREACHABLE
- Raise with reason string
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


class TestAssertSimple:
    """Test simple assert statement without message."""

    def test_assert_simple(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256):
    assert x > 0
"""
        ctx, fn = _lower_all_stmts(source)

        # Should have blocks: entry, assert_ok, assert_fail
        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        assert any("assert_ok" in label for label in block_labels)
        assert any("assert_fail" in label for label in block_labels)

        # Find the fail block and check it has revert
        for bb in fn._basic_block_dict.values():
            if "assert_fail" in bb.label.name:
                # Should end with revert instruction
                assert bb.is_terminated
                # Last instruction should be revert
                last_inst = list(bb.instructions)[-1]
                assert last_inst.opcode == "revert"

    def test_assert_with_boolean_condition(self):
        source = """
# @version ^0.4.0
@external
def foo(x: bool):
    assert x
"""
        ctx, fn = _lower_all_stmts(source)

        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        assert any("assert_ok" in label for label in block_labels)


class TestAssertUnreachable:
    """Test assert with UNREACHABLE."""

    def test_assert_unreachable(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256):
    assert x > 0, UNREACHABLE
"""
        ctx, fn = _lower_all_stmts(source)

        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        assert any("assert_ok" in label for label in block_labels)
        assert any("assert_fail" in label for label in block_labels)

        # Find the fail block and check it has invalid opcode
        for bb in fn._basic_block_dict.values():
            if "assert_fail" in bb.label.name:
                # invalid is a halting terminator, not a BB terminator
                assert bb.is_halting
                last_inst = list(bb.instructions)[-1]
                assert last_inst.opcode == "invalid"


class TestAssertWithReason:
    """Test assert with reason string."""

    def test_assert_with_literal_reason(self):
        source = '''
# @version ^0.4.0
@external
def foo(x: uint256):
    assert x > 0, "value must be positive"
'''
        ctx, fn = _lower_all_stmts(source)

        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        assert any("assert_ok" in label for label in block_labels)
        assert any("assert_fail" in label for label in block_labels)

        # Fail block should have revert (with encoded error)
        for bb in fn._basic_block_dict.values():
            if "assert_fail" in bb.label.name:
                assert bb.is_terminated
                last_inst = list(bb.instructions)[-1]
                assert last_inst.opcode == "revert"


class TestRaiseSimple:
    """Test bare raise statement."""

    def test_raise_bare(self):
        source = """
# @version ^0.4.0
@external
def foo():
    raise
"""
        ctx, fn = _lower_all_stmts(source)

        # Check that there's a revert instruction
        found_revert = False
        for bb in fn._basic_block_dict.values():
            for inst in bb.instructions:
                if inst.opcode == "revert":
                    found_revert = True
                    break

        assert found_revert


class TestRaiseUnreachable:
    """Test raise UNREACHABLE."""

    def test_raise_unreachable(self):
        source = """
# @version ^0.4.0
@external
def foo():
    raise UNREACHABLE
"""
        ctx, fn = _lower_all_stmts(source)

        # Check that there's an invalid instruction
        found_invalid = False
        for bb in fn._basic_block_dict.values():
            for inst in bb.instructions:
                if inst.opcode == "invalid":
                    found_invalid = True
                    break

        assert found_invalid


class TestRaiseWithReason:
    """Test raise with reason string."""

    def test_raise_with_literal_reason(self):
        source = '''
# @version ^0.4.0
@external
def foo():
    raise "something went wrong"
'''
        ctx, fn = _lower_all_stmts(source)

        # Check that there's a revert instruction
        found_revert = False
        for bb in fn._basic_block_dict.values():
            for inst in bb.instructions:
                if inst.opcode == "revert":
                    found_revert = True
                    break

        assert found_revert


class TestConditionalAssertRaise:
    """Test assert/raise in conditional contexts."""

    def test_assert_in_if(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256):
    if x > 10:
        assert x < 100
"""
        ctx, fn = _lower_all_stmts(source)

        # Should have both if and assert blocks
        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        assert any("then" in label for label in block_labels)
        assert any("assert_ok" in label for label in block_labels)

    def test_raise_in_else(self):
        source = """
# @version ^0.4.0
@external
def foo(x: uint256):
    if x > 0:
        pass
    else:
        raise
"""
        ctx, fn = _lower_all_stmts(source)

        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        assert any("else" in label for label in block_labels)

        # Check revert exists in some block
        found_revert = False
        for bb in fn._basic_block_dict.values():
            for inst in bb.instructions:
                if inst.opcode == "revert":
                    found_revert = True
                    break

        assert found_revert


class TestAssertInLoop:
    """Test assert in loop contexts."""

    def test_assert_in_for_loop(self):
        source = """
# @version ^0.4.0
@external
def foo():
    for i: uint256 in range(10):
        assert i < 5
"""
        ctx, fn = _lower_all_stmts(source)

        block_labels = [bb.label.name for bb in fn._basic_block_dict.values()]
        # Should have both loop and assert blocks
        assert any("for" in label for label in block_labels)
        assert any("assert_ok" in label for label in block_labels)
