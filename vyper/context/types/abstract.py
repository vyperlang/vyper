

class AbstractDataType:
    """
    Base class for abstract type classes.

    Abstract type classes are not assignable and should not implement any
    functionality other than simple comparison. They are inherited by type definition
    classes and used for broad comparisons based soley on data format with no
    consideration for syntax. For example, a function that accepts either `int128`
    or `uint256` might perform this comparison using `IntegerAbstractType`.
    """

    def compare_type(self, other) -> bool:
        try:
            return super().compare_type(other)
        except AttributeError:
            pass
        return isinstance(other, type(self))


class ArrayValueAbstractType(AbstractDataType):
    """
    Abstract data class for single-value types occupying multiple memory slots.
    """


class BytesAbstractType(AbstractDataType):
    """Abstract data class for bytes types (bytes32, bytes[])."""
    _id = "bytes"


class NumericAbstractType(AbstractDataType):
    """
    Abstract data class for numeric types (capable of arithmetic).
    """


class IntegerAbstractType(NumericAbstractType):
    """Abstract data class for integer numeric types (int128, uint256)."""


class FixedAbstractType(NumericAbstractType):
    """
    Abstract data class for decimal numeric types.

    Note that Vyper currently only has one decimal type - this class should
    still be used to expect decimal values in anticipation of multiple decimal
    types in a future release.
    """
