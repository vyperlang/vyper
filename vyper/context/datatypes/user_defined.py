from collections import (
    OrderedDict,
)
from vyper import (
    ast as vy_ast,
)
from vyper.context.utils import (
    check_call_args,
)
from vyper.exceptions import (
    StructureException,
)

from vyper.context.datatypes.functions import (
    Function,
)
from vyper.context.datatypes import (
    get_type_from_annotation,
)
from vyper.context.datatypes.bases import (
    UserDefinedType,
)
from vyper.context.datatypes.builtins import (
    AddressType,
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


class StructType(UserDefinedType):
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

    __slots__ = ('members',)

    def __init__(self, namespace, node):
        super().__init__(namespace, node)
        self._id = node.name
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
            self.members[member_name] = get_type_from_annotation(namespace, node.annotation)

    def from_annotation(self, namespace, node):
        # TODO
        return self.__init__(self.namespace, self.node)

    def __repr__(self):
        return f"<Struct Type '{self._id}'>"


class InterfaceType(UserDefinedType):
    """
    Meta-type object for interface types.

    Attributes
    ----------
    _id : str
        Name of the custom type.
    node : ClassDef
        Vyper AST node that defines this meta-type.
    """
    __slots__ = ('_id', 'node', 'functions', 'address')
    _as_array = True

    def __init__(self, namespace, node):
        super().__init__(namespace, node)
        self._id = node.name
        self.functions = {}
        namespace = self.namespace.copy('builtin')
        if isinstance(self.node, vy_ast.Module):
            functions = self._get_module_functions(namespace)
        elif isinstance(self.node, vy_ast.ClassDef):
            functions = self._get_class_functions(namespace)
        else:
            raise
        for func in functions:
            if func.name in namespace or func.name in self.functions:
                raise StructureException("Namespace collision", func.node)
            self.functions[func.name] = func

    def _get_class_functions(self, namespace):
        functions = []
        for node in self.node.body:
            if not isinstance(node, vy_ast.FunctionDef):
                raise StructureException("Interfaces can only contain function definitions", node)
            functions.append(Function(namespace, node, "public"))
        return functions

    def _get_module_functions(self, namespace):
        functions = []
        for node in self.node.get_children({'ast_type': "FunctionDef"}):
            if "public" in node.decorator_list:
                functions.append(Function(namespace, node))
        return functions

    def validate_implements(self, namespace):
        unimplemented = [i.name for i in self.functions.values() if namespace.get(i.name) != i]
        if unimplemented:
            raise StructureException(
                f"Contract does not implement all interface functions: {', '.join(unimplemented)}",
                self.node
            )

    def from_annotation(self, namespace, node):
        obj = super().__init__(namespace, node)
        check_call_args(node, 1)
        address = node.args[0]
        if isinstance(address, vy_ast.Hex):
            obj.address = address.value
        elif isinstance(address, vy_ast.Name):
            obj.address = namespace[address.id]
            if not isinstance(obj.address, AddressType):
                raise
        else:
            raise
        # TODO validate address

    def validate_literal(self, node):
        # TODO
        pass
