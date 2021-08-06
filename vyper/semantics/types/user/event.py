from collections import OrderedDict
from typing import Dict, List

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.exceptions import (
    EventDeclarationException,
    NamespaceCollision,
    StructureException,
)
from vyper.semantics.namespace import validate_identifier
from vyper.semantics.types.bases import DataLocation
from vyper.semantics.types.utils import (
    get_type_from_abi,
    get_type_from_annotation,
)
from vyper.semantics.validation.utils import validate_expected_type
from vyper.utils import keccak256


class Event:
    """
    Event type.

    Attributes
    ----------
    arguments : OrderedDict
        Event arguments.
    event_id : int
        Keccak of the event signature, converted to an integer. Used as the
        first topic when the event is emitted.
    indexed : list
        A list of booleans indicating if each argument within the event is
        indexed.
    name : str
        Name of the event.
    """

    def __init__(self, name: str, arguments: OrderedDict, indexed: List) -> None:
        for key in arguments:
            validate_identifier(key)
        self.name = name
        self.arguments = arguments
        self.indexed = indexed
        self.event_id = int(keccak256(self.signature.encode()).hex(), 16)

    @property
    def signature(self):
        return f"{self.name}({','.join(v.canonical_type for v in self.arguments.values())})"

    @classmethod
    def from_abi(cls, abi: Dict) -> "Event":
        """
        Generate an `Event` object from an ABI interface.

        Arguments
        ---------
        abi : dict
            An object from a JSON ABI interface, representing an event.

        Returns
        -------
        Event object.
        """
        members: OrderedDict = OrderedDict()
        indexed: List = [i["indexed"] for i in abi["inputs"]]
        for item in abi["inputs"]:
            members[item["name"]] = get_type_from_abi(item)
        return Event(abi["name"], members, indexed)

    @classmethod
    def from_EventDef(cls, base_node: vy_ast.EventDef) -> "Event":
        """
        Generate an `Event` object from a Vyper ast node.

        Arguments
        ---------
        base_node : EventDef
            Vyper ast node defining the event
        Returns
        -------
        Event
        """
        members: OrderedDict = OrderedDict()
        indexed: List = []

        if len(base_node.body) == 1 and isinstance(base_node.body[0], vy_ast.Pass):
            return Event(base_node.name, members, indexed)

        for node in base_node.body:
            if not isinstance(node, vy_ast.AnnAssign):
                raise StructureException("Events can only contain variable definitions", node)
            if node.value is not None:
                raise StructureException("Cannot assign a value during event declaration", node)
            if not isinstance(node.target, vy_ast.Name):
                raise StructureException("Invalid syntax for event member name", node.target)
            member_name = node.target.id
            if member_name in members:
                raise NamespaceCollision(
                    f"Event member '{member_name}' has already been declared", node.target
                )

            annotation = node.annotation
            if isinstance(annotation, vy_ast.Call) and annotation.get("func.id") == "indexed":
                validate_call_args(annotation, 1)
                if indexed.count(True) == 3:
                    raise EventDeclarationException(
                        "Event cannot have more than three indexed arguments", annotation
                    )
                indexed.append(True)
                annotation = annotation.args[0]
            else:
                indexed.append(False)

            members[member_name] = get_type_from_annotation(annotation, DataLocation.UNSET)

        return Event(base_node.name, members, indexed)

    def fetch_call_return(self, node: vy_ast.Call) -> None:
        validate_call_args(node, len(self.arguments))
        for arg, expected in zip(node.args, self.arguments.values()):
            validate_expected_type(arg, expected)

    def to_abi_dict(self) -> List[Dict]:
        return [
            {
                "name": self.name,
                "inputs": [
                    {"name": name, "type": typ.canonical_type, "indexed": idx}
                    for (name, typ), idx in zip(self.arguments.items(), self.indexed)
                ],
                "anonymous": False,
                "type": "event",
            }
        ]
