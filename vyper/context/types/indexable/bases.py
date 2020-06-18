from vyper.context.types.bases import BaseType


class IndexableType(BaseType):
    """
    Base class for indexable types such as arrays and mappings.

    Attributes
    ----------
    key_type: BaseType
        Type representing the index value for this object.
    value_type : BaseType
        Type representing the value(s) contained in this object.
    _id : str
        Name of the type.
    """

    def __init__(
        self, value_type, key_type, _id, is_constant: bool = False, is_public: bool = False
    ) -> None:
        super().__init__(is_constant, is_public)
        self.value_type = value_type
        self.key_type = key_type
        self._id = _id
