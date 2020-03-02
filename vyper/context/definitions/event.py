from collections import (
    OrderedDict,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.definitions.bases import (
    FunctionDefinition,
)
from vyper.context.types import (
    get_type_from_annotation,
)
from vyper.context.utils import (
    check_call_args,
)
from vyper.exceptions import (
    StructureException,
)


def get_event_from_node(node: vy_ast.AnnAssign):
    """
    Generates an event definition object from an ast node.

    Arguments
    ---------
    node : AnnAssign
        Vyper ast node to generate the event from.

    Returns
    -------
    Event object.
    """
    if node.value:
        raise StructureException("Cannot assign a value to an event", node.value)

    name = node.target.id
    arguments = OrderedDict()
    indexed = []
    check_call_args(node.annotation, 1)
    if not isinstance(node.annotation.args[0], vy_ast.Dict):
        raise StructureException("Invalid event declaration syntax", node.annotation.args[0])
    for key, value in zip(node.annotation.args[0].keys, node.annotation.args[0].values):
        if isinstance(value, vy_ast.Call):
            if value.func.id != "indexed":
                raise StructureException(f"Invalid keyword '{value.func.id}'", value.func)
            check_call_args(value, 1)
            indexed.append(True)
            value = value.args[0]
        else:
            indexed.append(False)
        arguments[key] = get_type_from_annotation(value)
    return Event(name, arguments, indexed)


class Event(FunctionDefinition):
    """
    Event definition object.

    Event are special functions that exiss as members of the builtin `log`
    object.

    Object attributes
    -----------------
    indexed : list
        A list of booleans indicating if each argument within the event is
        indexed.
    """

    __slots__ = ("indexed",)

    def __init__(self, name: str, arguments, indexed):
        super().__init__(name, arguments, len(arguments), None)
        self.indexed = indexed

    def __eq__(self, other):
        return (
            isinstance(other, Event) and
            self.name == other.name and
            self.arguments == other.arguments
        )
