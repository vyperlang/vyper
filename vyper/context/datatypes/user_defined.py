from collections import (
    OrderedDict,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.datatypes.bases import (
    MemberType,
)
from vyper.context.datatypes.builtins import (
    AddressType,
)
from vyper.context.functions import (
    Function,
)
from vyper.context.typecheck import (
    compare_types,
    get_type_from_annotation,
    get_type_from_node,
)
from vyper.context.utils import (
    check_call_args,
)
from vyper.exceptions import (
    StructureException,
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

    def get_type(self, namespace, base_node):
        members = OrderedDict()
        for node in base_node.body:
            if not isinstance(node, vy_ast.AnnAssign):
                raise StructureException("Structs can only contain variables", node)
            if node.value is not None:
                raise StructureException("Cannot assign a value during struct declaration", node)
            member_name = node.target.id
            if member_name in members:
                raise StructureException(
                    f"Struct member '{member_name}'' has already been declared", node.target
                )
            members[member_name] = get_type_from_annotation(namespace, node.annotation)
        return StructType(namespace, base_node.name, members)


class InterfaceMetaType(_BaseMetaType):

    """Metatype creator object for interface types."""

    __slots__ = ()
    _id = "contract"

    def get_type(self, namespace, node):
        return InterfaceType(namespace, node)


class StructType(MemberType):

    __slots__ = ()

    def __init__(self, namespace, _id, members):
        super().__init__(namespace)
        self._id = _id
        self.add_member_types(**members)

    def from_annotation(self, namespace, node):
        return type(self)(namespace, self._id, self.members)

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, 1)
        if not isinstance(node.args[0], vy_ast.Dict):
            raise StructureException("Struct values must be declared via dictionary", node.args[0])
        for key, value in zip(node.args[0].keys, node.args[0].values):
            if key is None or key.get('id') not in self.members:
                raise StructureException("Unknown struct member", value)
            value_type = get_type_from_node(self.namespace, value)
            compare_types(self.members[key.id], value_type, key)

    def __repr__(self):
        return f"<Struct Type '{self._id}'>"


class InterfaceType(MemberType):
    """
    Meta-type object for interface types.

    Attributes
    ----------
    _id : str
        Name of the custom type.
    node : ClassDef
        Vyper AST node that defines this meta-type.
    """
    __slots__ = ('node', 'address')
    _as_array = True

    def __init__(self, namespace, node):
        super().__init__(namespace)
        self._id = node.name
        self.node = node
        namespace = self.namespace.copy('builtin')
        if isinstance(node, vy_ast.Module):
            functions = self._get_module_functions(namespace, node)
        elif isinstance(node, vy_ast.ClassDef):
            functions = self._get_class_functions(namespace, node)
        else:
            raise
        for func in functions:
            if func.name in namespace or func.name in self.members:
                raise StructureException("Namespace collision", func.node)
        self.add_member_types(**{i.name: i for i in functions})

    def _get_class_functions(self, namespace, base_node):
        functions = []
        for node in base_node.body:
            if not isinstance(node, vy_ast.FunctionDef):
                raise StructureException("Interfaces can only contain function definitions", node)
            functions.append(Function(namespace, node, "public"))
        return functions

    def _get_module_functions(self, namespace, base_node):
        functions = []
        for node in base_node.get_children({'ast_type': "FunctionDef"}):
            if "public" in node.decorator_list:
                functions.append(Function(namespace, node))
        return functions

    def validate_implements(self, namespace):
        unimplemented = [i.name for i in self.members.values() if namespace.get(i.name) != i]
        if unimplemented:
            raise StructureException(
                f"Contract does not implement all interface functions: {', '.join(unimplemented)}",
                self.node
            )

    def from_annotation(self, namespace, node):
        # TODO
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
