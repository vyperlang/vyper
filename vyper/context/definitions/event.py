from collections import (
    OrderedDict,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.definitions.bases import (
    FunctionDefinition,
)
from vyper.context.definitions.variable import (
    get_variable_from_nodes,
)
from vyper.context.utils import (
    check_call_args,
)
from vyper.exceptions import (
    StructureException,
)


def get_event_from_node(namespace, node: vy_ast.AnnAssign):
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
        var = get_variable_from_nodes(namespace, key, value, None)
        arguments[key] = var
    return Event(namespace, name, arguments, indexed)


class Event(FunctionDefinition):

    __slots__ = ("indexed",)

    def __init__(
        self,
        namespace,
        name: str,
        arguments,
        indexed,
    ):
        super().__init__(namespace, name, "module", arguments, len(arguments), None)
        self.indexed = indexed

    def __eq__(self, other):
        return (
            isinstance(other, Event) and
            self.name == other.name and
            self.arguments == other.arguments
        )
