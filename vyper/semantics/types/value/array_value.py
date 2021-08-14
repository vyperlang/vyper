import math
from typing import Type

from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic, StructureException, UnexpectedValue
from vyper.semantics import validation

from ..abstract import ArrayValueAbstractType, BytesAbstractType
from ..bases import BasePrimitive, DataLocation, ValueTypeDefinition


class _ArrayValueDefinition(ValueTypeDefinition):
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

    is_dynamic_size = True

    def __repr__(self):
        return f"{self._id}[{self.length}]"

    def __init__(
        self,
        length: int = 0,
        location: DataLocation = DataLocation.MEMORY,
        is_immutable: bool = False,
        is_public: bool = False,
    ) -> None:
        super().__init__(location, is_immutable, is_public)
        self._length = length
        self._min_length = length

    @property
    def length(self):
        """
        Property method used to check the length of a type.
        """
        if self._length:
            return self._length
        return self._min_length

    @property
    def size_in_bytes(self):
        # the first slot (32 bytes) stores the actual length, and then we reserve
        # enough additional slots to store the data if it uses the max available length
        # because this data type is single-bytes, we make it so it takes the max 32 byte
        # boundary as it's size, instead of giving it a size that is not cleanly divisble by 32

        # TODO adding 64 here instead of 32 to be compatible with parser - fix this!
        return 64 + math.ceil(self.length / 32) * 32

    @property
    def canonical_type(self) -> str:
        return self._id.lower()

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


class _ArrayValuePrimitive(BasePrimitive):
    _type: Type[_ArrayValueDefinition]  # type: ignore

    @classmethod
    def from_annotation(
        cls,
        node: vy_ast.VyperNode,
        location: DataLocation = DataLocation.MEMORY,
        is_immutable: bool = False,
        is_public: bool = False,
    ) -> _ArrayValueDefinition:
        if not isinstance(node, vy_ast.Subscript):
            raise StructureException(
                f"Cannot declare {cls._id} type without a maximum length", node
            )
        if len(node.get_descendants(vy_ast.Subscript, include_self=True)) > 1:
            raise StructureException(f"Multidimensional {cls._id} arrays are not supported", node)
        if node.get("value.id") != cls._id:
            raise UnexpectedValue("Node id does not match type name")

        length = validation.utils.get_index_value(node.slice)  # type: ignore
        return cls._type(length, location, is_immutable, is_public)

    @classmethod
    def from_literal(cls, node: vy_ast.Constant) -> _ArrayValueDefinition:
        super().from_literal(node)
        length = len(node.value)

        obj = cls._type()
        obj.set_min_length(length)
        return obj


class BytesArrayDefinition(BytesAbstractType, ArrayValueAbstractType, _ArrayValueDefinition):
    _id = "Bytes"


class StringDefinition(ArrayValueAbstractType, _ArrayValueDefinition):
    _id = "String"


class BytesArrayPrimitive(_ArrayValuePrimitive):
    _id = "Bytes"
    _type = BytesArrayDefinition
    _valid_literal = (vy_ast.Bytes,)


class StringPrimitive(_ArrayValuePrimitive):
    _id = "String"
    _type = StringDefinition
    _valid_literal = (vy_ast.Str,)
