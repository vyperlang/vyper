"""
Tests for convert() built-in function.
"""
import pytest

from vyper.codegen_venom.expr import Expr
from vyper.venom.basicblock import IRVariable

from .conftest import get_expr_context


class TestConvertToBytesM:
    def test_bytesm_downcast_emits_clamp(self):
        """
        Regression test: bytesM downcast should emit an assertion (clamp)
        rather than silently truncating via masking.

        The generated code should contain shl to check that low bytes are zero.
        """
        source = """
# @version ^0.4.0
@external
def foo(x: bytes4) -> bytes2:
    return convert(x, bytes2)
"""
        ctx, node = get_expr_context(source)
        result = Expr(node, ctx).lower_value()
        assert isinstance(result, IRVariable)

        # Verify that the generated IR contains an assertion (shl + iszero + assert)
        # The clamp pattern is: shl(16, val) -> iszero -> assert
        fn = ctx.builder.fn
        found_shl = False
        found_assert = False
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "shl":
                    # Check for shl with shift amount of 16 (bytes2 * 8)
                    for op in inst.operands:
                        if getattr(op, "value", None) == 16:
                            found_shl = True
                            break
                if inst.opcode == "assert":
                    found_assert = True

        assert found_shl, "Expected shl(16, ...) instruction for bytes_clamp"
        assert found_assert, "Expected assert instruction for bytes_clamp"
