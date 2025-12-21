"""
Lower Vyper AST expressions to Venom IR.

This module handles the first stage of expression codegen: converting
Vyper AST literal and expression nodes into Venom IR operands.
"""
from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import AddressT, BytesM_T, BytesT, StringT
from vyper.utils import DECIMAL_DIVISOR, ceil32
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

from .context import VenomCodegenContext


class Expr:
    """Lower Vyper expressions to Venom IR."""

    def __init__(self, node: vy_ast.VyperNode, ctx: VenomCodegenContext):
        self.node = node.reduced()
        self.ctx = ctx
        self.builder = ctx.builder

    def lower(self) -> IROperand:
        """Dispatch to type-specific lowering method."""
        fn_name = f"lower_{type(self.node).__name__}"
        method = getattr(self, fn_name, None)
        if method is None:
            raise CompilerPanic(f"Unsupported expr: {type(self.node)}")
        return method()

    # === Literal Lowering ===

    def lower_Int(self) -> IRLiteral:
        """Lower integer literal."""
        return IRLiteral(self.node.value)

    def lower_Decimal(self) -> IRLiteral:
        """Lower decimal literal.

        Decimals are stored as fixed-point integers scaled by DECIMAL_DIVISOR (10^10).
        """
        val = self.node.value * DECIMAL_DIVISOR
        return IRLiteral(int(val))

    def lower_Hex(self) -> IRLiteral:
        """Lower hex literal (address or bytesN).

        For addresses: direct int conversion.
        For bytesN: left-padded (shifted left) to align in 32-byte word.
        """
        hexstr = self.node.value
        t = self.node._metadata["type"]

        if t == AddressT():
            return IRLiteral(int(hexstr, 16))

        elif isinstance(t, BytesM_T):
            n_bytes = (len(hexstr) - 2) // 2
            # Left-pad: shift value to occupy high bytes of 32-byte word
            val = int(hexstr, 16) << 8 * (32 - n_bytes)
            return IRLiteral(val)

        raise CompilerPanic(f"Unsupported Hex literal type: {t}")

    def lower_NameConstant(self) -> IRLiteral:
        """Lower True/False constants."""
        assert isinstance(self.node.value, bool)
        return IRLiteral(int(self.node.value))

    # === Bytelike Literals ===

    def lower_Bytes(self) -> IRVariable:
        """Lower bytes literal (b'...')."""
        return self._lower_bytelike(BytesT, self.node.value)

    def lower_HexBytes(self) -> IRVariable:
        """Lower hex bytes literal (x'...')."""
        assert isinstance(self.node.value, bytes)
        return self._lower_bytelike(BytesT, self.node.value)

    def lower_Str(self) -> IRVariable:
        """Lower string literal ('...')."""
        bytez = self.node.value.encode("utf-8")
        return self._lower_bytelike(StringT, bytez)

    def _lower_bytelike(self, typeclass: type, bytez: bytes) -> IRVariable:
        """Allocate memory and store bytes/string literal.

        Memory layout:
            ptr+0:  length (32 bytes)
            ptr+32: data[0:32] (right-padded with zeros)
            ptr+64: data[32:64] (if needed)
            ...

        Returns pointer to allocated memory.
        """
        bytez_length = len(bytez)
        btype = typeclass(bytez_length)

        # Allocate memory for length word + data
        ptr = self.ctx.new_internal_variable(btype)

        # Store length at ptr
        self.builder.mstore(IRLiteral(bytez_length), ptr)

        # Store data in 32-byte chunks, right-padded with zeros
        for i in range(0, bytez_length, 32):
            chunk = (bytez + b"\x00" * 31)[i : i + 32]
            word = int.from_bytes(chunk, "big")
            offset = self.builder.add(ptr, IRLiteral(32 + i))
            self.builder.mstore(IRLiteral(word), offset)

        return ptr
