from typing import Dict, List

from vyper import ast as vy_ast
from vyper.abi_types import ABI_GIntM
from vyper.exceptions import (
    EnumDeclarationException,
    StructureException,
    UnimplementedException,
    UnknownAttribute,
)
from vyper.semantics.namespace import validate_identifier
from vyper.semantics.types.bases import DataLocation, MemberTypeDefinition, ValueTypeDefinition
from vyper.semantics.validation.levenshtein_utils import get_levenshtein_error_suggestions


class EnumDefinition(MemberTypeDefinition, ValueTypeDefinition):
    def __init__(
        self,
        name: str,
        members: dict,
        location: DataLocation = DataLocation.MEMORY,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> None:
        self._id = name
        super().__init__(location, is_constant, is_public, is_immutable)
        for key, val in members.items():
            self.add_member(key, val)

    @property
    def abi_type(self):
        # note: not compatible with solidity enums - those have
        # ABI type uint8.
        return ABI_GIntM(m_bits=256, signed=False)

    def validate_numeric_op(self, node):
        allowed_ops = (vy_ast.BitOr, vy_ast.BitAnd, vy_ast.Invert, vy_ast.BitXor)
        if isinstance(node.op, allowed_ops):
            return
        # fallback to parent class error message
        super().validate_numeric_op(node)

    def validate_comparator(self, node):
        if isinstance(node.op, (vy_ast.Eq, vy_ast.NotEq, vy_ast.In, vy_ast.NotIn)):
            return
        # fallback to parent class error message
        super().validate_comparator(node)


class EnumPrimitive:
    """
    Enum type.

    Attributes
    ----------
    arguments : list of strings
    name : str
        Name of the element.
    """

    def __init__(self, name: str, members: dict) -> None:
        for key in members.keys():
            validate_identifier(key)
        self.name = name
        if len(members.keys()) > 256:
            raise EnumDeclarationException("Enums are limited to 256 members!")
        self.members = members

    def __repr__(self):
        arg_types = ",".join(repr(a) for a in self.members)
        return f"enum {self.name}({arg_types})"

    @property
    def signature(self):
        return f"{self.name}({','.join(v.canonical_abi_type for v in self.arguments)})"

    @classmethod
    def from_abi(cls, abi: Dict) -> "EnumPrimitive":
        """
        Generate an `Enum` object from an ABI interface.

        Arguments
        ---------
        abi : dict
            An object from a JSON ABI interface, representing an enum.

        Returns
        -------
        Enum object.
        """
        raise UnimplementedException("enum from ABI")

    @classmethod
    def from_EnumDef(cls, base_node: vy_ast.EnumDef) -> "EnumPrimitive":
        """
        Generate an `Enum` object from a Vyper ast node.

        Arguments
        ---------
        base_node : EnumDef
            Vyper ast node defining the enum
        Returns
        -------
        Enum
        """
        members: Dict = {}

        if len(base_node.body) == 1 and isinstance(base_node.body[0], vy_ast.Pass):
            raise EnumDeclarationException("Enum must have members")

        for i, node in enumerate(base_node.body):
            member_name = node.value.id
            if member_name in members:
                raise EnumDeclarationException(
                    f"Enum member '{member_name}' has already been declared", node.value
                )

            members[member_name] = i

        return cls(base_node.name, members)

    def fetch_call_return(self, node: vy_ast.Call) -> None:
        # TODO
        return None

    def to_abi_dict(self) -> List[Dict]:
        # TODO
        return []

    def get_member(self, key: str, node: vy_ast.Attribute) -> EnumDefinition:
        if key in self.members:
            return self.from_annotation(node.value)
        suggestions_str = get_levenshtein_error_suggestions(key, self.members, 0.3)
        raise UnknownAttribute(f"{self} has no member '{key}'. {suggestions_str}", node)

    def from_annotation(
        self,
        node: vy_ast.VyperNode,
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> EnumDefinition:
        if not isinstance(node, vy_ast.Name):
            raise StructureException("Invalid type", node)
        return EnumDefinition(
            self.name, self.members, location, is_constant, is_public, is_immutable
        )
