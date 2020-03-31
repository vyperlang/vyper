from collections import (
    OrderedDict,
)
from typing import (
    Union,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    namespace,
)
from vyper.context.definitions import (
    ContractFunction,
    Reference,
    get_definition_from_node,
    get_variable_from_nodes,
)
from vyper.context.types.bases import (
    MemberType,
)
from vyper.context.utils import (
    compare_types,
    validate_call_args,
)
from vyper.exceptions import (
    InterfaceViolation,
    NamespaceCollision,
    StructureException,
    UnknownAttribute,
    VariableDeclarationException,
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
    """
    __slots__ = ()

    def __init__(self):
        pass


class StructMetaType(_BaseMetaType):

    """Metatype creator object for struct types."""

    __slots__ = ()
    _id = "struct"

    def get_type(self, base_node: vy_ast.ClassDef):
        members = OrderedDict()
        for node in base_node.body:
            if not isinstance(node, vy_ast.AnnAssign):
                raise StructureException("Structs can only contain variables", node)
            if node.value is not None:
                raise StructureException("Cannot assign a value during struct declaration", node)
            if not isinstance(node.target, vy_ast.Name):
                raise StructureException("Invalid syntax for struct member name", node.target)
            member_name = node.target.id
            if member_name in members:
                raise NamespaceCollision(
                    f"Struct member '{member_name}'' has already been declared", node.target
                )
            members[member_name] = get_variable_from_nodes(member_name, node.annotation, None)
        return StructType(base_node.name, members)


class StructType(MemberType):

    __slots__ = ()
    _as_array = True

    def __init__(self, _id, members):
        self._id = _id
        super().__init__()
        self.add_type_members(**members)

    @property
    def type(self):
        raise StructureException("Struct type cannot be assigned directly, it must be called")

    def _compare_type(self, other):
        return super()._compare_type(other) and self._id == other._id

    def from_annotation(self, node: vy_ast.VyperNode):
        return type(self)(self._id, self.members)

    def fetch_call_return(self, node: vy_ast.Call):
        validate_call_args(node, 1)
        if not isinstance(node.args[0], vy_ast.Dict):
            raise VariableDeclarationException(
                "Struct values must be declared via dictionary", node.args[0]
            )
        novalue = next((i for i in self.members.values() if not hasattr(i, 'type')), None)
        if novalue:
            raise VariableDeclarationException(
                f"Struct contains a {type(novalue).__name__} and cannot be declared as a literal",
                node
            )

        members = self.members.copy()
        for key, value in zip(node.args[0].keys, node.args[0].values):
            if key is None or key.get('id') not in members:
                raise UnknownAttribute("Unknown or duplicate struct member", key or value)
            value_type = get_definition_from_node(value).type
            compare_types(members.pop(key.id).type, value_type, key)
        if members:
            raise VariableDeclarationException(
                f"Struct declaration does not define all fields: {', '.join(list(members))}", node
            )
        return Reference.from_type(self, self._id, is_readonly=True)


class InterfaceMetaType(_BaseMetaType):

    """Metatype creator object for interface types."""

    __slots__ = ()
    _id = "contract"

    def get_type_from_abi(self, name, abi: dict):
        members = OrderedDict()
        for item in [i for i in abi if i.get('type') == "function"]:
            func = ContractFunction.from_abi(item)
            if func.name in members:
                # TODO overloaded functions
                raise NamespaceCollision(
                    f"ABI '{name}' contains multiple functions named '{func.name}'"
                )
            members[func.name] = func
        return InterfaceType(name, members)

    def get_type(self, node: Union[vy_ast.ClassDef, vy_ast.Module]):
        if isinstance(node, vy_ast.Module):
            members = self._get_module_functions(node)
        elif isinstance(node, vy_ast.ClassDef):
            members = self._get_class_functions(node)
        else:
            raise StructureException("Invalid syntax for interface definition", node)
        for func in members.values():
            if func.name in namespace:
                raise NamespaceCollision(func.name, func.node)

        return InterfaceType(node.name, members)

    def _get_class_functions(self, base_node: vy_ast.ClassDef):
        functions = OrderedDict()
        for node in base_node.body:
            if not isinstance(node, vy_ast.FunctionDef):
                raise StructureException("Interfaces can only contain function definitions", node)
            functions[node.name] = ContractFunction.from_FunctionDef(node, is_public=True)
        return functions

    def _get_module_functions(self, base_node: vy_ast.Module):
        functions = OrderedDict()
        for node in base_node.get_children(vy_ast.FunctionDef):
            if "public" in [i.id for i in node.decorator_list]:
                func = ContractFunction.from_FunctionDef(node, include_defaults=True)
                functions[node.name] = func
        for node in base_node.get_children(vy_ast.AnnAssign, {'annotation.func.id': "public"}):
            functions[node.target.id] = ContractFunction.from_AnnAssign(node)
        return functions


class InterfaceType(MemberType):
    """
    Meta-type object for interface types.

    Attributes
    ----------
    _id : str
        Name of the custom type.
    """
    __slots__ = ('address',)
    _as_array = True
    _type_members = {'address': "address"}

    @property
    def type(self):
        raise StructureException(
            "Interface type cannot be assigned directly, it must be called with an address"
        )

    def __init__(self, _id, members):
        self._id = _id
        super().__init__()
        self.add_type_members(**members)

    def validate_implements(self, node: vy_ast.AnnAssign):
        unimplemented = [
            i.name for i in self.members.values() if
            i.name not in namespace['self'].members or
            not hasattr(namespace['self'].members[i.name], '_compare_signature') or
            not namespace['self'].members[i.name]._compare_signature(i)
        ]
        if unimplemented:
            raise InterfaceViolation(
                f"Contract does not implement all interface functions: {', '.join(unimplemented)}",
                node
            )

    def from_annotation(self, node: vy_ast.VyperNode):
        return type(self)(self._id, self.members)

    def fetch_call_return(self, node: vy_ast.Call):
        validate_call_args(node, 1)
        value = get_definition_from_node(node.args[0]).type
        compare_types(value, namespace['address'], node.args[0])

        return Reference.from_type(self, self._id, is_readonly=True)
