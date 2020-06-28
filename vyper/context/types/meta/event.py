from collections import OrderedDict
from typing import List

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.context.types.bases import DataLocation
from vyper.context.types.utils import get_type_from_annotation
from vyper.context.validation.utils import validate_expected_type
from vyper.exceptions import (
    EventDeclarationException,
    NamespaceCollision,
    StructureException,
)


class Event:
    """
    Event type.

    Attributes
    ----------
    arguments : OrderedDict
        Event arguments.
    indexed : list
        A list of booleans indicating if each argument within the event is
        indexed.
    name : str
        Name of the event.
    """

    def __init__(self, name: str, arguments: OrderedDict, indexed: List) -> None:
        self.name = name
        self.arguments = arguments
        self.indexed = indexed

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
