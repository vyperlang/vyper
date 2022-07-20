from vyper import ast as vy_ast
from vyper.abi_types import ABI_Address, ABIType
from vyper.exceptions import InvalidLiteral
from vyper.utils import checksum_encode, is_checksum_encoded

from .base import AttributableT, VyperType
from .bytestrings import BytesT


class BoolT(VyperType):
    _id = "bool"
    _as_array = True
    _valid_literal = (vy_ast.NameConstant,)

    def validate_boolean_op(self, node: vy_ast.BoolOp) -> None:
        return

    def validate_numeric_op(
        self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp, vy_ast.AugAssign]
    ) -> None:
        if isinstance(node.op, vy_ast.Not):
            return
        super().validate_numeric_op(node)

    @property
    def abi_type(self) -> ABIType:
        return ABI_Bool()

    def validate_literal(cls, node: vy_ast.Constant) -> None:
        super().validate_literal(node)
        if node.value is None:
            raise InvalidLiteral("Invalid literal for type 'bool'", node)


class BytesM_T(VyperType):
    length: int

    @property
    def _id(self):
        return f"bytes{self.length}"

    @property
    def abi_type(self) -> ABIType:
        return ABI_BytesM(self.length)


    _as_array = True
    _valid_literal = (vy_ast.Hex,)

    @classmethod
    def validate_literal(cls, node: vy_ast.Constant):
        super().validate_literal(node)
        val = node.value
        m = cls._length

        if len(val) != 2 + 2 * m:
            raise InvalidLiteral("Invalid literal for type bytes32", node)

        nibbles = val[2:]  # strip leading 0x
        if nibbles not in (nibbles.lower(), nibbles.upper()):
            raise InvalidLiteral(f"Cannot mix uppercase and lowercase for bytes{m} literal", node)


class IntegerT(VyperType):
    """
    Attributes
    ----------
    bits : int
        Number of bits the value occupies in memory
    is_signed : bool
        Is the value signed?
    """

    def __init__(self, is_signed, bits):
        self.is_signed: bool = is_signed
        self.bits: int = bits

    @property
    def invalid_ops(self):
        if not self.is_signed:
            return (vy_ast.USub,)
        return ()

    def validate_numeric_op(
        self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp, vy_ast.AugAssign]
    ) -> None:
        if isinstance(node.op, self.invalid_ops):
            raise InvalidOperation(f"Cannot perform {node.op.description} on {self}", node)

        if isinstance(node.op, vy_ast.Pow):
            if isinstance(node, vy_ast.BinOp):
                left, right = node.left, node.right
            elif isinstance(node, vy_ast.AugAssign):
                left, right = node.target, node.value
            else:
                raise CompilerPanic(f"Unexpected node type for numeric op: {type(node).__name__}")

            value_bits = self._bits - (1 if self._is_signed else 0)

            # TODO double check: this code seems duplicated with constant eval
            # constant folding ensures one of `(left, right)` is never a literal
            if isinstance(left, vy_ast.Int):
                if left.value >= 2 ** value_bits:
                    raise OverflowException(
                        "Base is too large, calculation will always overflow", left
                    )
                elif left.value < -(2 ** value_bits):
                    raise OverflowException(
                        "Base is too small, calculation will always underflow", left
                    )
            elif isinstance(right, vy_ast.Int):
                if right.value < 0:
                    raise InvalidOperation("Cannot calculate a negative power", right)
                if right.value > value_bits:
                    raise OverflowException(
                        "Power is too large, calculation will always overflow", right
                    )
            else:
                msg = (
                    "Cannot apply an overflow check on exponentiation when both "
                    "the base and power are unknown at compile-time."
                )
                if not self._is_signed:
                    msg = (
                        f"{msg} To perform this operation without an overflow check, use "
                        f"`pow_mod256({left.node_source_code}, {right.node_source_code})`"
                    )
                raise InvalidOperation(msg, node)

    def validate_comparator(self, node: vy_ast.Compare) -> None:
        # all comparators are valid on numeric types
        return

    @property
    def abi_type(self) -> ABIType:
        return ABI_GIntM(self._bits, self._is_signed)


# shortcuts
T_UINT256 = IntegerT(False, 256)
T_UINT8 = IntegerT(False, 8)
T_INT256 = IntegerT(False, 256)
T_INT128 = IntegerT(False, 128)


class _NumericT(BasePrimitive):
    _as_array = True
    _bounds: Tuple[int, int]

    @classmethod
    def validate_literal(cls, node: vy_ast.Constant):
        super().validate_literal(node)
        lower, upper = cls._bounds
        if node.value < lower:
            raise OverflowException(f"Value is below lower bound for given type ({lower})", node)
        if node.value > upper:
            raise OverflowException(f"Value exceeds upper bound for given type ({upper})", node)


class DecimalT(_NumericT):
    _bounds = (SizeLimits.MIN_AST_DECIMAL, SizeLimits.MAX_AST_DECIMAL)
    _bits = 168  # TODO generalize
    _decimal_places = 10  # TODO generalize
    _id = "decimal"
    _is_signed = True
    _invalid_op = vy_ast.Pow
    _valid_literal = (vy_ast.Decimal,)

    @property
    def abi_type(self) -> ABIType:
        return ABI_FixedMxN(self._bits, self._decimal_places, self._is_signed)


# maybe this even deserves its own module, address.py
class AddressT(AttributableT):
    _as_array = True
    _id = "address"
    _valid_literal = (vy_ast.Hex,)
    _type_members = {
        "balance": T_UINT256,
        "codehash": T_BYTES32,
        "codesize": T_UINT256,
        "is_contract": BoolT(),
        "code": BytesT(),
    }

    @property
    def abi_type(self) -> ABIType:
        return ABI_Address()

    @classmethod
    def validate_literal(cls, node: vy_ast.Constant):
        super().validate_literal(node)
        addr = node.value
        if len(addr) != 42:
            n_bytes = (len(addr) - 2) // 2
            raise InvalidLiteral(f"Invalid address. Expected 20 bytes, got {n_bytes}.", node)

        if not is_checksum_encoded(addr):
            raise InvalidLiteral(
                "Address checksum mismatch. If you are sure this is the right "
                f"address, the correct checksummed form is: {checksum_encode(addr)}",
                node,
            )
