from vyper import ast as vy_ast
from vyper.abi_types import ABI_Bytes, ABI_String, ABIType
from vyper.exceptions import CompilerPanic, StructureException, UnexpectedNodeType, UnexpectedValue
from vyper.semantics.types.base import VyperType
from vyper.semantics.types.utils import get_index_value
from vyper.utils import ceil32


class _UnknownLength(object):
    pass


UNKNOWN_LENGTH = _UnknownLength()


# TODO: make this a trait which DynArray also inherits from
class _DynLength(VyperType):
    pass


class _BytestringT(_DynLength):
    """
    Private base class for single-value types which occupy multiple memory slots
    and where a maximum length must be given via a subscript (string, bytes).

    The length can be generic (for bytestrings which come from interfaces,
    e.g. Bytes[...]). This is indicated with `_length is UNKNOWN_LENGTH`.

    Attributes
    ----------
    _length : int
        The maximum allowable length of the data within the type.
    """

    # this is a carveout because currently we allow dynamic arrays of
    # bytestrings, but not static arrays of bytestrings
    _as_darray = True
    _as_hashmap_key = True
    _equality_attrs = ("_length",)
    _is_bytestring: bool = True

    def __init__(self, length: int | _UnknownLength = UNKNOWN_LENGTH) -> None:
        super().__init__()

        self._length = length

    def __repr__(self):
        length = self.length
        if self.length is None:
            length = "..."
        return f"{self._id}[{length}]"

    def _addl_dict_fields(self):
        return {"length": self.length}

    @property
    def length(self):
        """
        Property method used to check the length of a type.
        """
        if self._length is UNKNOWN_LENGTH:
            return None
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
            # sanity check
            raise CompilerPanic("unreachable")

    @property
    def size_in_bytes(self):
        # the first slot (32 bytes) stores the actual length, and then we
        # reserve enough additional slots to store the data. allocate 32-byte
        # aligned buffer for the data.
        return 32 + ceil32(self.length)

    def compare_type(self, other):
        if not super().compare_type(other):
            return False

        # can assign any Bytes[N] to Bytes[...]
        if self._length is UNKNOWN_LENGTH:
            return True

        # cannot assign Bytes[...] to Bytes[N] without going through convert()
        if other._length is UNKNOWN_LENGTH:
            return True

        return self._length >= other._length

    @classmethod
    def from_annotation(cls, node: vy_ast.VyperNode) -> "_BytestringT":
        if not isinstance(node, vy_ast.Subscript):
            raise StructureException(
                f"Cannot declare {cls._id} type without a maximum length, e.g. {cls._id}[5]", node
            )

        if node.get("value.id") != cls._id:
            raise UnexpectedValue("Node id does not match type name")

        length = get_index_value(node.slice)

        if length is None:
            return cls(UNKNOWN_LENGTH)

        return cls(length)

    @classmethod
    def from_literal(cls, node: vy_ast.Constant) -> "_BytestringT":
        if not isinstance(node, cls._valid_literal):
            raise UnexpectedNodeType(f"Not a {cls._id}: {node}")
        return cls(len(node.value))


class BytesT(_BytestringT):
    typeclass = "bytes"

    _id = "Bytes"
    _valid_literal = (vy_ast.Bytes,)

    @property
    def abi_type(self) -> ABIType:
        return ABI_Bytes(self.length)


class StringT(_BytestringT):
    typeclass = "string"

    _id = "String"
    _valid_literal = (vy_ast.Str,)

    @property
    def abi_type(self) -> ABIType:
        return ABI_String(self.length)
