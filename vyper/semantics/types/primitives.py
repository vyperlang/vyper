# primitive types which occupy one word, like ints and addresses

from typing import Tuple, Union

from vyper import ast as vy_ast
from vyper.abi_types import ABI_Address, ABI_Bool, ABI_BytesM, ABI_FixedMxN, ABI_GIntM, ABIType
from vyper.exceptions import CompilerPanic, InvalidLiteral, InvalidOperation, OverflowException
from vyper.utils import SizeLimits, checksum_encode, int_bounds, is_checksum_encoded

from .base import VyperType
from .bytestrings import BytesT


class _PrimT(VyperType):
    _is_prim_word = True
    _equality_attrs: tuple = ()


class BoolT(_PrimT):
    _id = "bool"
    _as_array = True
    _valid_literal = (vy_ast.NameConstant,)

    def validate_boolean_op(self, node: vy_ast.BoolOp) -> None:
        return

    def validate_numeric_op(
        self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp, vy_ast.AugAssign]
    ) -> None:
        if not isinstance(node.op, vy_ast.Not):
            self._raise_invalid_op(node)

    @property
    def abi_type(self) -> ABIType:
        return ABI_Bool()

    def validate_literal(self, node: vy_ast.Constant) -> None:
        super().validate_literal(node)
        if node.value is None:
            raise InvalidLiteral("Invalid literal for type 'bool'", node)


RANGE_1_32 = list(range(1, 33))


# one-word bytesM with m possible bytes set, e.g. bytes1..bytes32
class BytesM_T(_PrimT):
    _as_array = True
    _valid_literal = (vy_ast.Hex,)

    _equality_attrs = ("m",)

    def __init__(self, m):
        super().__init__()
        self.m: int = m

    @property
    def _id(self):
        return f"bytes{self.m}"

    # convenience for backwards API compat
    @property
    def length(self):
        return self.m

    @property
    def abi_type(self) -> ABIType:
        return ABI_BytesM(self.m)

    @classmethod
    def all(cls):
        return [cls(m) for m in RANGE_1_32]

    def validate_literal(self, node: vy_ast.Constant) -> None:
        super().validate_literal(node)

        assert isinstance(node, vy_ast.Hex)  # keep mypy happy

        val = node.value

        if node.n_bytes != self.m:
            raise InvalidLiteral("Invalid literal for type {self}", node)

        nibbles = val[2:]  # strip leading 0x
        if nibbles not in (nibbles.lower(), nibbles.upper()):
            raise InvalidLiteral(f"Cannot mix uppercase and lowercase for {self} literal", node)

    def compare_type(self, other: VyperType) -> bool:
        if not super().compare_type(other):
            return False
        assert isinstance(other, BytesM_T)

        return self.m == other.m


class NumericT(_PrimT):
    _as_array = True
    _is_signed: bool
    _bits: int
    _invalid_ops: tuple
    bounds: Tuple[int, int]

    def validate_literal(self, node: vy_ast.Constant) -> None:
        super().validate_literal(node)
        lower, upper = self.bounds
        if node.value < lower:
            raise OverflowException(f"Value is below lower bound for given type ({lower})", node)
        if node.value > upper:
            raise OverflowException(f"Value exceeds upper bound for given type ({upper})", node)

    def validate_numeric_op(
        self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp, vy_ast.AugAssign]
    ) -> None:
        if isinstance(node.op, self._invalid_ops):
            self._raise_invalid_op(node)

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


class IntegerT(NumericT):
    """
    General integer type. All signed and unsigned ints from uint8 thru int256

    Attributes
    ----------
    bits : int
        Number of bits the value occupies in memory
    is_signed : bool
        Is the value signed?
    """

    _valid_literal = (vy_ast.Int,)
    _equality_attrs = ("is_signed", "bits")

    def __init__(self, is_signed, bits):
        super().__init__()
        self.is_signed: bool = is_signed
        self.bits: int = bits

    @property
    def _id(self):
        u = "u" if not self.is_signed else ""
        return f"{u}int{self.bits}"

    @property
    def bounds(self):
        return int_bounds(self.is_signed, self.bits)

    @property
    def _invalid_ops(self):
        if not self.is_signed:
            return (vy_ast.USub,)
        return ()

    @classmethod
    # TODO maybe cache these three classmethods
    def signeds(cls) -> Tuple["IntegerT", ...]:
        return tuple(cls(is_signed=True, bits=i * 8) for i in RANGE_1_32)

    @classmethod
    def unsigneds(cls) -> Tuple["IntegerT", ...]:
        return tuple(cls(is_signed=False, bits=i * 8) for i in RANGE_1_32)

    @classmethod
    def all(cls) -> Tuple["IntegerT", ...]:
        return cls.signeds() + cls.unsigneds()

    # backwards compatible api, TODO: remove me
    @property
    def _bits(self):
        return self.bits

    # backwards compatible api, TODO: remove me
    @property
    def _is_signed(self):
        return self.is_signed

    @property
    def abi_type(self) -> ABIType:
        return ABI_GIntM(self.bits, self.is_signed)

    def compare_type(self, other: VyperType) -> bool:
        if not super().compare_type(other):
            return False
        assert isinstance(other, IntegerT)  # mypy

        return self.is_signed == other.is_signed and self.bits == other.bits


# shortcuts
UINT256_T = IntegerT(False, 256)
UINT8_T = IntegerT(False, 8)
INT256_T = IntegerT(False, 256)
INT128_T = IntegerT(False, 128)

BYTES32_T = BytesM_T(32)
BYTES4_T = BytesM_T(4)


class DecimalT(NumericT):
    bounds = (SizeLimits.MIN_AST_DECIMAL, SizeLimits.MAX_AST_DECIMAL)

    _bits = 168  # TODO generalize
    _decimal_places = 10  # TODO generalize
    _id = "decimal"
    _is_signed = True
    _invalid_ops = (vy_ast.Pow,)
    _valid_literal = (vy_ast.Decimal,)

    _equality_attrs = ("_bits", "_decimal_places")

    @property
    def abi_type(self) -> ABIType:
        return ABI_FixedMxN(self._bits, self._decimal_places, self._is_signed)


# maybe this even deserves its own module, address.py
class AddressT(_PrimT):
    _as_array = True
    _id = "address"
    _valid_literal = (vy_ast.Hex,)
    _type_members = {
        "balance": UINT256_T,
        "codehash": BYTES32_T,
        "codesize": UINT256_T,
        "is_contract": BoolT(),
        "code": BytesT(),
    }

    @property
    def abi_type(self) -> ABIType:
        return ABI_Address()

    def validate_literal(self, node: vy_ast.Constant) -> None:
        super().validate_literal(node)
        assert isinstance(node, vy_ast.Hex)  # keep mypy happy
        if node.n_bytes != 20:
            raise InvalidLiteral(f"Invalid address. Expected 20 bytes, got {node.n_bytes}.", node)

        addr = node.value
        if not is_checksum_encoded(addr):
            raise InvalidLiteral(
                "Address checksum mismatch. If you are sure this is the right "
                f"address, the correct checksummed form is: {checksum_encode(addr)}",
                node,
            )
