from collections import OrderedDict

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.context.types.bases import DataLocation, MemberTypeDefinition
from vyper.context.types.indexable.mapping import MappingDefinition
from vyper.context.types.utils import get_type_from_annotation
from vyper.context.validation.utils import validate_expected_type
from vyper.exceptions import (
    NamespaceCollision,
    StructureException,
    UnknownAttribute,
    VariableDeclarationException,
)


class StructDefinition(MemberTypeDefinition):
    def __init__(
        self,
        _id: str,
        members: dict,
        location: DataLocation = DataLocation.MEMORY,
        is_immutable: bool = False,
        is_public: bool = False,
    ) -> None:
        self._id = _id
        super().__init__(location, is_immutable, is_public)
        for key, type_ in members.items():
            self.add_member(key, type_)

    def compare_type(self, other):
        return super().compare_type(other) and self._id == other._id


class StructPrimitive:

    _is_callable = True
    _as_array = True

    def __init__(self, _id, members):
        self._id = _id
        self.members = members

    def __repr__(self):
        return f"{self._id} declaration object"

    def compare_type(self, other):
        return False

    def from_annotation(
        self,
        node: vy_ast.VyperNode,
        location: DataLocation = DataLocation.UNSET,
        is_immutable: bool = False,
        is_public: bool = False,
    ) -> StructDefinition:
        if not isinstance(node, vy_ast.Name):
            raise StructureException("Invalid type assignment", node)
        return StructDefinition(self._id, self.members, location, is_immutable, is_public)

    def fetch_call_return(self, node: vy_ast.Call) -> StructDefinition:
        validate_call_args(node, 1)
        if not isinstance(node.args[0], vy_ast.Dict):
            raise VariableDeclarationException(
                "Struct values must be declared via dictionary", node.args[0]
            )
        if next((i for i in self.members.values() if isinstance(i, MappingDefinition)), False,):
            raise VariableDeclarationException(
                "Struct contains a mapping and so cannot be declared as a literal", node
            )

        members = self.members.copy()
        for key, value in zip(node.args[0].keys, node.args[0].values):
            if key is None or key.get("id") not in members:
                raise UnknownAttribute("Unknown or duplicate struct member", key or value)
            validate_expected_type(value, members.pop(key.id))
        if members:
            raise VariableDeclarationException(
                f"Struct declaration does not define all fields: {', '.join(list(members))}", node,
            )

        return StructDefinition(self._id, self.members)


def build_primitive_from_node(base_node: vy_ast.EventDef) -> StructPrimitive:
    """
    Generate a `StructPrimitive` object from a Vyper ast node.

    Arguments
    ---------
    node : EventDef
        Vyper ast node defining the struct
    Returns
    -------
    StructPrimitive
        Primitive struct type
    """

    members: OrderedDict = OrderedDict()
    for node in base_node.body:
        if not isinstance(node, vy_ast.AnnAssign):
            raise StructureException("Structs can only variable definitions", node)
        if node.value is not None:
            raise StructureException("Cannot assign a value during struct declaration", node)
        if not isinstance(node.target, vy_ast.Name):
            raise StructureException("Invalid syntax for struct member name", node.target)
        member_name = node.target.id
        if member_name in members:
            raise NamespaceCollision(
                f"Struct member '{member_name}' has already been declared", node.target
            )
        members[member_name] = get_type_from_annotation(node.annotation, DataLocation.UNSET)

    return StructPrimitive(base_node.name, members)
