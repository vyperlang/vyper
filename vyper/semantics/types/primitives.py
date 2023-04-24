# primitive types which occupy one word, like ints and addresses

from decimal import Decimal
from functools import cached_property
from typing import Tuple, Union

from vyper import ast as vy_ast
from vyper.abi_types import ABI_Address, ABI_Bool, ABI_BytesM, ABI_FixedMxN, ABI_GIntM, ABIType
from vyper.exceptions import CompilerPanic, InvalidLiteral, InvalidOperation, OverflowException
from vyper.utils import checksum_encode, int_bounds, is_checksum_encoded

from .base import VyperType
from .bytestrings import BytesT


class _PrimT(VyperType):
    _is_prim_word = True
    _equality_attrs: tuple = ()
    _as_hashmap_key = True
    _as_array = True


# should inherit from uint8?
class BoolT(_PrimT):
    _id = "bool"
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
    _valid_literal = (vy_ast.Hex,)

    _equality_attrs = ("m",)

    def __init__(self, m):
        super().__init__()
        self.m: int = m

    @property
    def _id(self):
        return f"bytes{self.m}"

    @property
    def m_bits(self):
        return self.m * 8

    # convenience for backwards API compat
    @property
    def length(self):
        return self.m

    @property
    def abi_type(self) -> ABIType:
        return ABI_BytesM(self.m)

    @classmethod
    def all(cls) -> Tuple["BytesM_T", ...]:
        return tuple(cls(m) for m in RANGE_1_32)

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
    _is_signed: bool
    _bits: int
    _invalid_ops: tuple

    # the type this can assume in the AST
    ast_type: type

    @property
    def ast_bounds(self):
        raise NotImplementedError("should be overridden!")

    # get the integer bounds on IR values of this type.
    # note the distinction for decimals: ast_bounds will return a Decimal,
    # int_bounds will return the fully expanded int range.
    @cached_property
    def int_bounds(self) -> Tuple[int, int]:
        return int_bounds(signed=self.is_signed, bits=self.bits)

    @cached_property
    def bits(self) -> int:
        return self._bits

    @cached_property
    def is_signed(self) -> bool:
        return self._is_signed

    def validate_literal(self, node: vy_ast.Constant) -> None:
        super().validate_literal(node)
        lower, upper = self.ast_bounds
        if node.value < lower:
            raise OverflowException(f"Value is below lower bound for given type ({lower})", node)
        if node.value > upper:
            raise OverflowException(f"Value exceeds upper bound for given type ({upper})", node)

    def validate_numeric_op(
        self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp, vy_ast.AugAssign]
    ) -> None:
        if isinstance(node.op, self._invalid_ops):
            self._raise_invalid_op(node)

        def _get_lr():
            if isinstance(node, vy_ast.BinOp):
                return node.left, node.right
            elif isinstance(node, vy_ast.AugAssign):
                return node.target, node.value
            else:
                raise CompilerPanic(f"Unexpected node type for numeric op: {type(node).__name__}")

        if isinstance(node.op, (vy_ast.LShift, vy_ast.RShift)):
            if self._bits != 256:
                raise InvalidOperation(
                    f"Cannot perform {node.op.description} on non-int256/uint256 type!", node
                )

        if isinstance(node.op, vy_ast.Pow):
            left, right = _get_lr()

            value_bits = self._bits - (1 if self._is_signed else 0)

            # TODO double check: this code seems duplicated with constant eval
            # constant folding ensures one of `(left, right)` is never a literal
            if isinstance(left, vy_ast.Int):
                if left.value >= 2**value_bits:
                    raise OverflowException(
                        "Base is too large, calculation will always overflow", left
                    )
                elif left.value < -(2**value_bits):
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

    ast_type = int

    def __init__(self, is_signed, bits):
        super().__init__()
        self._is_signed = is_signed
        self._bits = bits

    @cached_property
    def _id(self):
        u = "u" if not self.is_signed else ""
        return f"{u}int{self.bits}"

    @cached_property
    def ast_bounds(self) -> Tuple[int, int]:
        return int_bounds(self.is_signed, self.bits)

    @cached_property
    def _invalid_ops(self):
        invalid_ops = (vy_ast.Not,)
        if not self.is_signed:
            return invalid_ops + (vy_ast.USub,)
        return invalid_ops

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

    @cached_property
    def abi_type(self) -> ABIType:
        return ABI_GIntM(self.bits, self.is_signed)

    def compare_type(self, other: VyperType) -> bool:
        if not super().compare_type(other):
            return False
        assert isinstance(other, IntegerT)  # mypy

        return self.is_signed == other.is_signed and self.bits == other.bits


# helper function for readability.
# returns a uint<N> type.
def UINT(bits):
    return IntegerT(False, bits)


# helper function for readability.
# returns an int<N> type.
def SINT(bits):
    return IntegerT(True, bits)


class DecimalT(NumericT):
    _bits = 168  # TODO generalize
    _decimal_places = 10  # TODO generalize
    _id = "decimal"
    _is_signed = True
    _invalid_ops = (vy_ast.Pow, vy_ast.BitAnd, vy_ast.BitOr, vy_ast.BitXor, vy_ast.Not)
    _valid_literal = (vy_ast.Decimal,)

    _equality_attrs = ("_bits", "_decimal_places")

    ast_type = Decimal

    @cached_property
    def abi_type(self) -> ABIType:
        return ABI_FixedMxN(self._bits, self._decimal_places, self._is_signed)

    @cached_property
    def decimals(self) -> int:
        # Alias for API compatibility with codegen
        return self._decimal_places

    @cached_property
    def divisor(self) -> int:
        return 10**self.decimals

    @cached_property
    def epsilon(self) -> Decimal:
        return 1 / Decimal(self.divisor)

    @cached_property
    def ast_bounds(self) -> Tuple[Decimal, Decimal]:
        return self.decimal_bounds

    @cached_property
    def decimal_bounds(self) -> Tuple[Decimal, Decimal]:
        lo, hi = int_bounds(signed=self.is_signed, bits=self.bits)
        DIVISOR = Decimal(self.divisor)
        return lo / DIVISOR, hi / DIVISOR


# maybe this even deserves its own module, address.py
# should inherit from uint160?
class AddressT(_PrimT):
    _id = "address"
    _valid_literal = (vy_ast.Hex,)
    _type_members = {
        "balance": UINT(256),
        "codehash": BytesM_T(32),
        "codesize": UINT(256),
        "is_contract": BoolT(),
        "code": BytesT(),
    }

    @cached_property
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
