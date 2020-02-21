from collections import (
    OrderedDict,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.datatypes.types import (
    ArrayType,
    InterfaceType,
    StructType,
)
from vyper.context.datatypes.functions import (
    Function,
)
from vyper.context.utils import (
    get_leftmost_id,
)
from vyper.exceptions import (
    StructureException,
)


class _BaseMetaType:
    """
    Private inherited class common to all classes representing vyper meta-types.

    A meta-type is an object used to instantiate a type object. Meta-types must
    include a `get_type` method that returns an appropriate type when called with
    a vyper AST node.

    Object Attributes
    -----------------
    namespace : Namespace
        The namespace object that this object exists within.
    """
    __slots__ = ('namespace', 'base_type')
    enclosing_scope = "builtin"

    def __init__(self, namespace, base_type):
        self.namespace = namespace
        self.base_type = base_type

    def get_type(self, node):
        """
        Returns a type class for the given node.

        Arguments
        ---------
        node : VyperNode
            AST node from AnnAssign.annotation, outlining the type
            to be created.

        Returns
        -------
        _BaseType
            If the base_type member of this object has an _as_array member
            and the node argument includes a subscript, the return type will
            be ArrayType. Otherwise it will be base_type.
        """
        if getattr(self.base_type, '_as_array', False) and isinstance(node, vy_ast.Subscript):
            obj = ArrayType(self.namespace, node)
        else:
            obj = self.base_type(self.namespace, node)
        obj._introspect()
        return obj


class _BaseMetaTypeCreator:
    """
    Private inherited class common to all classes representing vyper meta-types.

    A meta-type creator is an object used to instantiate a meta-type object.
    This is used to defining custom data types such structs and interfaces.

    Meta-type creators must include a `get_meta_type` method that returns an
    appropriate meta-type when called with a vyper AST node.

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


class BuiltinMetaType(_BaseMetaType):
    """
    Meta-type object for builtin types.

    This object is used for builtin type classes that include the _id member.

    Attributes
    ----------
    base_type : _BaseType
        Type class that this object instantiates when called.
    """
    __slots__ = ('base_type',)


class StructMetaTypeCreator(_BaseMetaTypeCreator):

    """Metatype creator object for struct types."""

    __slots__ = ()
    _id = "struct"

    def get_meta_type(self, node):
        return StructMetaType(self.namespace, node)


class StructMetaType(_BaseMetaType):
    """
    Meta-type object for struct types.

    Attributes
    ----------
    _id : str
        Name of the custom type.
    node : ClassDef
        Vyper AST node that defines this meta-type.
    members : OrderedDict
        A dictionary of {name: TypeObject} for each member of this meta-type.
    """

    __slots__ = ('_id', 'node', 'members')

    def __init__(self, namespace, node):
        super().__init__(namespace, StructType)
        self.node = node
        self._id = node.name

    @property
    def enclosing_scope(self):
        return self.node.enclosing_scope

    def _introspect(self):
        self.members = OrderedDict()
        for node in self.node.body:
            if not isinstance(node, vy_ast.AnnAssign):
                raise StructureException("Structs can only contain variables", node)
            if node.value is not None:
                raise StructureException("Cannot assign a value during struct declaration", node)
            member_name = node.target.id
            if member_name in self.members:
                raise StructureException(
                    f"Struct member '{member_name}'' has already been declared", node.target
                )
            type_name = get_leftmost_id(node.annotation)
            self.members[member_name] = self.namespace[type_name].get_type(node.annotation)

    def __repr__(self):
        return f"<Struct Type '{self._id}'>"


class InterfaceMetaTypeCreator(_BaseMetaTypeCreator):

    """Metatype creator object for interface types."""

    __slots__ = ()
    _id = "contract"

    def get_meta_type(self, node):
        return InterfaceMetaType(self.namespace, node)


class InterfaceMetaType(_BaseMetaType):
    """
    Meta-type object for interface types.

    Attributes
    ----------
    _id : str
        Name of the custom type.
    node : ClassDef
        Vyper AST node that defines this meta-type.
    """
    __slots__ = ('_id', 'node', 'functions')

    def __init__(self, namespace, node):
        super().__init__(namespace, InterfaceType)
        self.node = node
        self._id = node.name
        self.functions = {}

    @property
    def enclosing_scope(self):
        return self.node.enclosing_scope

    def _introspect(self):
        for node in self.node.body:
            if not isinstance(node, vy_ast.FunctionDef):
                raise StructureException("Interfaces can only contain function definitions", node)
            func = Function(self.namespace, node)

        pass
