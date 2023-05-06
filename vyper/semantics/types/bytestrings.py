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

    Types for literals are initialized to the literal's length.

    Attributes
    ----------
    _length : int
        The length of the data within the type.
    """

    # this is a carveout because currently we allow dynamic arrays of
    # bytestrings, but not static arrays of bytestrings
    _as_darray = True
    _as_hashmap_key = True
    _equality_attrs: tuple = ("_length",)
    _is_bytestring: bool = True
    _is_literal: bool = False

    def __init__(self, length: int = 0) -> None:
        super().__init__()

        self._length = length

    def __repr__(self):
        return f"{self._id}[{self.length}]"

    @property
    def length(self):
        """
        Property method used to check the length of a type.
        """
        return self._length

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
            # at the point that validate_literal is called
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

    def compare_type(self, other):
        if not super().compare_type(other):
            return False

        if self._length and other._length:
            # when comparing two literals, invert the comparison result so that the smaller
            # type can be widened by deriving the larger of common types during annotation
            if self._is_literal and other._is_literal:
                return self._length <= other._length

            # otherwise, ensure that the current length fits within the other
            return self._length >= other._length

        # relax typechecking if length has not been set for other type
        # (e.g. JSON ABI import) so that it can be updated in annotation phase
        if self._length:
            return True

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
        t.set_length(len(node.value))
        t._is_literal = True
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
