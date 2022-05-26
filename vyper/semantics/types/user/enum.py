from typing import Dict, List

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.exceptions import EnumDeclarationException, NamespaceCollision, StructureException
from vyper.semantics.namespace import validate_identifier
from vyper.semantics.types.bases import DataLocation
from vyper.semantics.types.utils import (
    generate_abi_type,
    get_type_from_abi,
    get_type_from_annotation,
)
from vyper.semantics.validation.utils import validate_expected_type
from vyper.utils import keccak256


class Enum:
    """
    Enum type.

    Attributes
    ----------
    arguments : list of strings
    name : str
        Name of the element.
    """

    def __init__(self, name: str, arguments: List) -> None:
        for key in arguments:
            validate_identifier(key)
        self.name = name
        self.arguments = arguments

    def __repr__(self):
        arg_types = ",".join(repr(a) for a in self.arguments)
        return f"enum {self.name}({arg_types})"

    @property
    def signature(self):
        return f"{self.name}({','.join(v.canonical_abi_type for v in self.arguments)})"

    @classmethod
    def from_abi(cls, abi: Dict) -> "Enum":
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
        members: List = List()
        return Enum(abi["name"], abi["inputs"])

    @classmethod
    def from_EnumDef(cls, base_node: vy_ast.EnumDef) -> "Enum":
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
        members: List = []

        if len(base_node.body) == 1 and isinstance(base_node.body[0], vy_ast.Pass):
            return Enum(base_node.name, members)

        for node in base_node.body:
            member_name = node.value.id
            if member_name in members:
                raise NamespaceCollision(
                    f"Enum member '{member_name}' has already been declared", node.value
                )

            members.append(member_name)

        return Enum(base_node.name, members)

    def fetch_call_return(self, node: vy_ast.Call) -> None:
        # TODO
        return None

    def to_abi_dict(self) -> List[Dict]:
        # TODO
        return []