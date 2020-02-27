from collections import (
    OrderedDict,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.typecheck import (
    compare_types,
    get_type_from_node,
)
from vyper.context.utils import (
    check_call_args,
)
from vyper.exceptions import (
    StructureException,
)


class Event:
    """
    Represents an event: `EventName({attr: value, .. })`

    Attributes
    ----------
    members : OrderedDict
        A dictionary of {field: {'type': TypeObject, 'indexed': bool}} representing each
        member in the event.
    namespace : Namespace
        The namespace object that this type exists within.

    # TODO
    """

    __slots__ = ("namespace", "name", "annotation", "members")

    def __init__(self, namespace, name, annotation, value):
        self.namespace = namespace
        self.name = name
        self.annotation = annotation
        node = self.annotation.args[0]
        self.members = OrderedDict()
        for key, value in zip(node.keys, node.values):
            self.members[key] = {"indexed": False}
            if isinstance(value, vy_ast.Call):
                if value.func.id != "indexed":
                    raise StructureException(
                        f"Invalid keyword '{value.func.id}'", value.func
                    )
                check_call_args(value, 1)
                self.members[key]["indexed"] = True
                value = value.args[0]
            self.members[key]["type"] = type(self.namespace[value.id])(self.namespace)

    def __eq__(self, other):
        return isinstance(other, Event) and self.members == other.members

    @property
    def enclosing_scope(self):
        return self.annotation.enclosing_scope

    def validate_call(self, node):
        check_call_args(node, len(self.members))
        for value, key in zip(node.args, self.members):
            typ = get_type_from_node(self.namespace, value)
            compare_types(self.members[key]["type"], typ, value)
