from vyper import ast as vy_ast
from vyper.abi_types import ABI_Bytes, ABI_String, ABIType
from vyper.exceptions import CompilerPanic, StructureException, UnexpectedNodeType, UnexpectedValue
from vyper.semantics.types.base import VyperType
from vyper.semantics.types.utils import get_index_value
from vyper.utils import ceil32


class _BytestringT(VyperType):
    """
    Private base class for single-value types which occupy multiple memory slots
    and where a maximum length must be given via a subscript (string, bytes).

    Types for literals have an inferred minimum length. For example, `b"hello"`
    has a length of 5 of more and so can be used in an operation with `bytes[5]`
    or `bytes[10]`, but not `bytes[4]`. Upon comparison to a fixed length type,
    the minimum length is discarded and the type assumes the fixed length it was
    compared against.

    Attributes
    ----------
    _length : int
        The maximum allowable length of the data within the type.
    _min_length: int
        The minimum length of the data within the type. Used when the type
        is applied to a literal definition.
    """

    # this is a carveout because currently we allow dynamic arrays of
    # bytestrings, but not static arrays of bytestrings
    _as_darray = True
    _as_hashmap_key = True
    _equality_attrs = ("_length", "_min_length")
    _is_bytestring: bool = True

    def __init__(self, length: int = 0) -> None:
        super().__init__()

        self._length = length
        self._min_length = length

    def __repr__(self):
        return f"{self._id}[{self.length}]"

    @property
    def length(self):
        """
        Property method used to check the length of a type.
        """
        if self._length:
            return self._length
        return self._min_length

    @property
    def maxlen(self):
        """
        Alias for backwards compatibility.
        """
        return self.length

    def validate_literal(self, node: vy_ast.Constant) -> None:
        super().validate_literal(node)

        if len(node.value) != self.length:
            # should always be constructed with correct length
            # at the point that validate_literal is calle.d
            raise CompilerPanic("unreachable")

    @property
    def size_in_bytes(self):
        # the first slot (32 bytes) stores the actual length, and then we reserve
        # enough additional slots to store the data if it uses the max available length
        # because this data type is single-bytes, we make it so it takes the max 32 byte
        # boundary as it's size, instead of giving it a size that is not cleanly divisble by 32

        return 32 + ceil32(self.length)

    def set_length(self, length):
        """
        Sets the exact length of the type.

        May only be called once, and only on a type that does not yet have
        a fixed length.
        """
        if self._length:
            raise CompilerPanic("Type already has a fixed length")
        self._length = length
        self._min_length = length

    def set_min_length(self, min_length):
        """
        Sets the minimum length of the type.

        May only be used to increase the minimum length. May not be called if
        an exact length has been set.
        """
        if self._length:
            raise CompilerPanic("Type already has a fixed length")
        if self._min_length > min_length:
            raise CompilerPanic("Cannot reduce the min_length of ArrayValueType")
        self._min_length = min_length

    def compare_type(self, other):
        if not super().compare_type(other):
            return False

        # CMC 2022-03-18 TODO this method should be refactored so it does not have side effects

        # when comparing two literals, both now have an equal min-length
        if not self._length and not other._length:
            min_length = max(self._min_length, other._min_length)
            self.set_min_length(min_length)
            other.set_min_length(min_length)
            return True

        # comparing a defined length to a literal causes the literal to have a fixed length
        if self._length:
            if not other._length:
                other.set_length(max(self._length, other._min_length))
            return self._length >= other._length

        return other.compare_type(self)

    @classmethod
    def from_annotation(cls, node: vy_ast.VyperNode) -> "_BytestringT":
        if not isinstance(node, vy_ast.Subscript) or not isinstance(node.slice, vy_ast.Index):
            raise StructureException(
                f"Cannot declare {cls._id} type without a maximum length, e.g. {cls._id}[5]", node
            )

        if node.get("value.id") != cls._id:
            raise UnexpectedValue("Node id does not match type name")

        length = get_index_value(node.slice)  # type: ignore
        # return cls._type(length, location, is_constant, is_public, is_immutable)
        return cls(length)

    @classmethod
    def from_literal(cls, node: vy_ast.Constant) -> "_BytestringT":
        if not isinstance(node, cls._valid_literal):
            raise UnexpectedNodeType(f"Not a {cls._id}: {node}")
        t = cls()
        t.set_min_length(len(node.value))
        return t


class BytesT(_BytestringT):
    _id = "Bytes"
    _valid_literal = (vy_ast.Bytes,)

    @property
    def abi_type(self) -> ABIType:
        return ABI_Bytes(self.length)


class StringT(_BytestringT):
    _id = "String"
    _valid_literal = (vy_ast.Str,)

    @property
    def abi_type(self) -> ABIType:
        return ABI_String(self.length)
