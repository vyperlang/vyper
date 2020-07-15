class AbstractDataType:
    """
    Base class for abstract type classes.

    Abstract type classes are not assignable and should not implement any
    functionality other than simple comparison. They are inherited by type definition
    classes and used for broad comparisons based soley on data format with no
    consideration for syntax. For example, a function that accepts either `int128`
    or `uint256` might perform this comparison using `IntegerAbstractType`.
    """

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
    """Abstract data class for bytes types (bytes32, bytes[])."""

    _description = "bytes"
    _id = "bytes"


class NumericAbstractType(AbstractDataType):
    """
    Abstract data class for numeric types (capable of arithmetic).
    """

    _description = "numeric value"


class IntegerAbstractType(NumericAbstractType):
    """Abstract data class for integer numeric types (int128, uint256)."""

    _description = "integer"


class FixedAbstractType(NumericAbstractType):
    """
    Abstract data class for decimal numeric types.

    Note that Vyper currently only has one decimal type - this class should
    still be used to expect decimal values in anticipation of multiple decimal
    types in a future release.
    """

    _description = "decimal"
