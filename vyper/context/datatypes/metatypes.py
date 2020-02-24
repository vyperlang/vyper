from vyper.context.datatypes.types import (
    InterfaceType,
    StructType,
)


class _BaseMetaType:
    """
    Private inherited class common to all classes representing vyper meta-types.

    A meta-type is an object used to instantiate a user-defined type object.
    This is used to define custom data types such structs and interfaces.

    Meta-types must include a `get_type` method that returns an
    appropriate type when called with a vyper AST node.

    Class Attributes
    ----------------
    _id : str
        The name that this object is assigned within the namespace.

    Object Attributes
    -----------------
    namespace : Namespace
        The namespace object that this object exists within.
    """
    __slots__ = ('namespace',)
    enclosing_scope = "builtin"

    def __init__(self, namespace):
        self.namespace = namespace


class StructMetaType(_BaseMetaType):

    """Metatype creator object for struct types."""

    __slots__ = ()
    _id = "struct"

    def get_type(self, namespace, node):
        return StructType(namespace, node)


class InterfaceMetaType(_BaseMetaType):

    """Metatype creator object for interface types."""

    __slots__ = ()
    _id = "contract"

    def get_type(self, namespace, node):
        return InterfaceType(namespace, node)
