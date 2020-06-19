from vyper import ast as vy_ast
from vyper.context import validation
from vyper.context.types.abstract import (
    ArrayValueAbstractType,
    BytesAbstractType,
)
from vyper.context.types.bases import BasePureType, ValueTypeDefinition
from vyper.exceptions import CompilerPanic, StructureException


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

    def __repr__(self):
        return f"{self._id}[{self.length}]"

    def __init__(self, length: int = 0, is_constant: bool = False, is_public: bool = False) -> None:
        super().__init__(is_constant, is_public)
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


class _ArrayValuePureType(BasePureType):

    @classmethod
    def from_annotation(cls, node, is_constant: bool = False, is_public: bool = False):
        if len(node.get_descendants(vy_ast.Subscript, include_self=True)) > 1:
            raise StructureException("Multidimensional arrays are not supported", node)

        length = validation.utils.get_index_value(node.get("slice") or node)
        return cls._type(length, is_constant, is_public)

    @classmethod
    def from_literal(cls, node):
        obj = super().from_literal(node)

        if isinstance(node, vy_ast.Hex):
            length = len(node.value) // 2 - 1
        else:
            length = len(node.value)

        obj.set_min_length(length)
        return obj


class BytesArrayDefinition(BytesAbstractType, ArrayValueAbstractType, _ArrayValueDefinition):
    _id = "bytes"


class StringDefinition(ArrayValueAbstractType, _ArrayValueDefinition):
    _id = "string"


class BytesArrayPureType(_ArrayValuePureType):
    _id = "bytes"
    _type = BytesArrayDefinition
    _valid_literal = (vy_ast.Bytes, vy_ast.Hex)


class StringPureType(_ArrayValuePureType):
    _id = "string"
    _type = StringDefinition
    _valid_literal = vy_ast.Str
