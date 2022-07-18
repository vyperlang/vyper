from vyper import ast as vy_ast
from vyper.abi_types import ABI_Address, ABIType
from vyper.exceptions import InvalidLiteral
from vyper.utils import checksum_encode, is_checksum_encoded

from ..bases import BasePrimitive, MemberTypeDefinition, ValueTypeDefinition
from .array_value import BytesArrayDefinition
from .boolean import BoolDefinition
from .bytes_fixed import Bytes32Definition
from .numeric import Uint256Definition  # type: ignore


class AddressT(AttributableT):
    _as_array = True
    _id = "address"
    _valid_literal = (vy_ast.Hex,)
    _type_members = {
        "balance": Uint256Definition(is_constant=True),
        "codehash": Bytes32Definition(is_constant=True),
        "codesize": Uint256Definition(is_constant=True),
        "is_contract": BoolDefinition(is_constant=True),
        "code": BytesArrayDefinition(is_constant=True),
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


# including so mypy does not complain while we are generating types dynamically
class Bytes32Definition(BytesMDefinition):

    # included for compatibility with bytes array methods
    length = 32
    _length = 32
    _min_length = 32


class AbstractNumericDefinition(ValueTypeDefinition):
    """
    Private base class for numeric definitions.

    Attributes
    ----------
    _bits : int
        Number of bits the value occupies in memory
    _is_signed : bool
        Is the value signed?
    _invalid_op : VyperNode, optional
        Vyper ast node, or list of nodes, that is not a valid operator for binary
        operations on this type.
    """

    _invalid_op: Optional[Type[vy_ast.VyperNode]] = None
    _bits: int
    _is_signed: bool

    def validate_numeric_op(
        self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp, vy_ast.AugAssign]
    ) -> None:
        if self._invalid_op and isinstance(node.op, self._invalid_op):
            raise InvalidOperation(f"Cannot perform {node.op.description} on {self}", node)

        if isinstance(node.op, vy_ast.Pow):
            if isinstance(node, vy_ast.BinOp):
                left, right = node.left, node.right
            elif isinstance(node, vy_ast.AugAssign):
                left, right = node.target, node.value
            else:
                raise CompilerPanic(f"Unexpected node type for numeric op: {type(node).__name__}")

            value_bits = self._bits - (1 if self._is_signed else 0)

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


class _SignedIntegerDefinition(AbstractNumericDefinition):
    """
    Private base class for signed integer definitions.
    """

    _is_signed = True

    @property
    def _id(self):
        return f"int{self._bits}"


class _UnsignedIntegerDefinition(AbstractNumericDefinition):
    """
    Private base class for unsigned integer definitions.
    """

    _is_signed = False
    _invalid_op = vy_ast.USub

    @property
    def _id(self):
        return f"uint{self._bits}"


class _NumericPrimitive(BasePrimitive):

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


# definitions

for i in range(32):
    bits = 8 * (i + 1)
    sint = f"Int{bits}Definition"
    uint = f"Uint{bits}Definition"
    # class Int128Definition(SignedIntegerAbstractType, _SignedIntegerDefinition):
    #    _bits = 128
    sint_def = type(sint, (SignedIntegerAbstractType, _SignedIntegerDefinition), {"_bits": bits})
    # class Uint256Definition(UnsignedIntegerAbstractType, _UnsignedIntegerDefinition):
    #    _bits = 256
    uint_def = type(
        uint, (UnsignedIntegerAbstractType, _UnsignedIntegerDefinition), {"_bits": bits}
    )

    globals()[sint] = sint_def
    globals()[uint] = uint_def

    globals()[f"Int{bits}Primitive"] = type(
        f"Int{bits}Primitive",
        (_NumericPrimitive,),
        {
            "_bounds": int_bounds(signed=True, bits=bits),
            "_id": f"int{bits}",
            "_type": sint_def,
            "_valid_literal": (vy_ast.Int,),
        },
    )

    globals()[f"Uint{bits}Primitive"] = type(
        f"Uint{bits}Primitive",
        (_NumericPrimitive,),
        {
            "_bounds": int_bounds(signed=False, bits=bits),
            "_id": f"uint{bits}",
            "_type": uint_def,
            "_valid_literal": (vy_ast.Int,),
        },
    )


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
