from typing import Tuple

from vyper.codegen.types import INTEGER_TYPES, SIGNED_INTEGER_TYPES, UNSIGNED_INTEGER_TYPES


class AbstractDataType:
    """
    Base class for abstract type classes.

    Abstract type classes are not assignable and should not implement any
    functionality other than simple comparison. They are inherited by type definition
    classes and used for broad comparisons based soley on data format with no
    consideration for syntax. For example, a function that accepts either `int128`
    or `uint256` might perform this comparison using `IntegerAbstractType`.
    """

    # tuple of string type names used in `vyper.functions.signatures` to support abstract types
    # as input types in builtin functions. this is a temporary solution until the `functions`
    # subpackage is refactored - @iamdefinitelyahuman
    _id_list: Tuple

    def compare_type(self, other):
        try:
            return super().compare_type(other)
        except AttributeError:
            pass
        return isinstance(other, type(self))

    def __repr__(self):
        value = super().__repr__()
        if value == object.__repr__(self):
            # use `_description` when no parent class overrides the default python repr
            return self._description
        return value


class ArrayValueAbstractType(AbstractDataType):
    """
    Abstract data class for single-value types occupying multiple memory slots.
    """

    _description = "fixed size bytes array or string"


class BytesAbstractType(AbstractDataType):
    """Abstract data class for bytes types (bytes, bytesM)."""

    _description = "bytes"
    _id = "bytes"


class BytesMAbstractType(BytesAbstractType):
    """Abstract data class for fixed bytes types (bytes32, bytes4, ...)"""

    _description = "bytes<M> where M<=32"


class NumericAbstractType(AbstractDataType):
    """
    Abstract data class for numeric types (capable of arithmetic).
    """

    _description = "numeric value"
    _id_list: Tuple = ("decimal",) + tuple(INTEGER_TYPES)


class IntegerAbstractType(NumericAbstractType):
    """Abstract data class for integer numeric types (signed and unsigned)."""

    _description = "integer"
    _id_list: Tuple = tuple(INTEGER_TYPES)


class SignedIntegerAbstractType(IntegerAbstractType):
    """Abstract data class for signed integer numeric types."""

    _description = "signed integer"
    _id_list: Tuple = tuple(SIGNED_INTEGER_TYPES)


class UnsignedIntegerAbstractType(IntegerAbstractType):
    """Abstract data class for unsigned integer numeric types."""

    _description = "unsigned integer"
    _id_list: Tuple = tuple(UNSIGNED_INTEGER_TYPES)


# TODO rename me to DecimalAbstractType (confusion with BytesM - fixed bytes)
class FixedAbstractType(NumericAbstractType):
    """
    Abstract data class for decimal numeric types.

    Note that Vyper currently only has one decimal type - this class should
    still be used to expect decimal values in anticipation of multiple decimal
    types in a future release.
    """

    _description = "decimal"
