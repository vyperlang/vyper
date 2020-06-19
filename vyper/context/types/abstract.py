

class AbstractDataType:
    """
    Base class for abstract type classes.

    Abstract type classes are uncastable, inherited types used for comparison.
    For example, a function that accepts either `int128` or `uint256` might
    perform this comparison using the `IntegerBase` abstract type.
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
