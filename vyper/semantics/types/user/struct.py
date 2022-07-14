from collections import OrderedDict

from vyper import ast as vy_ast
from vyper.abi_types import ABI_Tuple, ABIType
from vyper.ast.validation import validate_call_args
from vyper.exceptions import (
    InvalidAttribute,
    NamespaceCollision,
    StructureException,
    UnknownAttribute,
    VariableDeclarationException,
)
from vyper.semantics.namespace import validate_identifier
from vyper.semantics.types.bases import DataLocation, MemberTypeDefinition, ValueTypeDefinition
from vyper.semantics.types.indexable.mapping import MappingDefinition
from vyper.semantics.types.utils import get_type_from_annotation
from vyper.semantics.validation.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.validation.utils import validate_expected_type


class StructT(AttributableT, SimpleGettableT):
    _is_callable = True
    _as_array = True

    def __init__(self, _id, members):
        self._id = _id

        for k, v in members:
            validate_identifier(k)
            self.add_member(k, v)

    @classmethod
    def from_ast_def(cls, base_node: vy_ast.StructDef) -> "StructT":
        """
        Generate a `StructT` object from a Vyper ast node.

        Arguments
        ---------
        node : StructDef
            Vyper ast node defining the struct
        Returns
        -------
        StructT
            Struct type
        """

        struct_name = base_node.name
        members: List[Tuple(str, VyperType)] = {}
        for node in base_node.body:
            if not isinstance(node, vy_ast.AnnAssign):
                raise StructureException(
                    "Struct declarations can only contain variable definitions", node
                )
            if node.value is not None:
                raise StructureException("Cannot assign a value during struct declaration", node)
            if not isinstance(node.target, vy_ast.Name):
                raise StructureException("Invalid syntax for struct member name", node.target)
            member_name = node.target.id
            members.append(member_name, type_from_annotation(node.annotation))

        return cls(struct_name, members)

    def __repr__(self):
        return f"{self._id} declaration object"

    # TODO check me
    def compare_type(self, other):
        return super().compare_type(other) and self._id == other._id

    @property
    def size_in_bytes(self):
        return sum(i.size_in_bytes for i in self.members.values())

    @property
    def abi_type(self) -> ABIType:
        return ABI_Tuple([t.abi_type for t in self.members.values()])

    def to_abi_dict(self, name: str = "") -> dict:
        components = [t.to_abi_dict(name=k) for k, t in self.members.items()]
        return {"name": name, "type": "tuple", "components": components}

    # TODO breaking change: use kwargs instead of dict
    def fetch_call_return(self, node: vy_ast.Call) -> StructT:
        validate_call_args(node, 1)
        if not isinstance(node.args[0], vy_ast.Dict):
            raise VariableDeclarationException(
                "Struct values must be declared via dictionary", node.args[0]
            )
        if next((i for i in self.members.values() if isinstance(i, MappingDefinition)), False):
            raise VariableDeclarationException(
                "Struct contains a mapping and so cannot be declared as a literal", node
            )

        members = self.members.copy()
        keys = list(self.members.keys())
        for i, (key, value) in enumerate(zip(node.args[0].keys, node.args[0].values)):
            if key is None or key.get("id") not in members:
                suggestions_str = get_levenshtein_error_suggestions(key.get("id"), members, 1.0)
                raise UnknownAttribute(
                    f"Unknown or duplicate struct member. {suggestions_str}", key or value
                )
            expected_key = keys[i]
            if key.id != expected_key:
                raise InvalidAttribute(
                    "Struct keys are required to be in order, but got "
                    f"`{key.id}` instead of `{expected_key}`. (Reminder: the "
                    f"keys in this struct are {list(self.members.items())})",
                    key,
                )

            validate_expected_type(value, members.pop(key.id))

        if members:
            raise VariableDeclarationException(
                f"Struct declaration does not define all fields: {', '.join(list(members))}", node
            )

        return StructT(self._id, self.members)
