from collections import (
    OrderedDict,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.definitions.bases import (
    CallableDefinition,
    PublicDefinition,
)
from vyper.context.definitions.utils import (
    get_definition_from_node,
    get_type_from_annotation,
)
from vyper.context.definitions.values import (
    get_variable_from_nodes,
)
from vyper.context.utils import (
    compare_types,
    validate_call_args,
)
from vyper.exceptions import (
    EventDeclarationException,
    InvalidType,
    StructureException,
    TypeMismatch,
)


class MappingDefinition(PublicDefinition):
    """
    Represents a storage mapping: `map(key_type, value_type)`

    Attributes
    ----------
    key_type : ValueType
        Type object representing the mapping key.
    value_type : _BaseType
        Type object representing the mapping value.
    """
    _id = "map"

    def __init__(self, name=None):
        super().__init__(name)

    def _compare_type(self, other):
        return (
            super()._compare_type(other) and
            self.key_type == other.key_type and
            self.value == other.value
        )

    @classmethod
    def from_ann_assign(cls, name, annotation: vy_ast.VyperNode, value, is_public):
        if value is not None:
            raise
        self = cls(name)
        self.is_public = is_public
        validate_call_args(annotation, 2)
        self.key_type = get_type_from_annotation(annotation.args[0])

        self.value = get_variable_from_nodes(f"{name}_value", annotation.args[1], None)
        return self

    def __repr__(self):
        return f"map({self.key_type}, {self.value})"

    def get_index(self, node: vy_ast.Subscript):
        idx_type = get_definition_from_node(node.slice.value).type
        try:
            compare_types(self.key_type, idx_type, node.slice)
        except TypeMismatch:
            raise InvalidType(f"Invalid key type for mapping: {idx_type}", node.slice) from None
        return self.value

    def get_signature(self):
        arguments = (self.key_type,)
        if hasattr(self.value, 'get_signature'):
            new_args, return_type = self.value.get_signature()
            return arguments + new_args, return_type
        return arguments, self.value.type


class Event(CallableDefinition):
    """
    Event definition object.

    Event are special functions that exist as members of the builtin `log`
    object.

    Object attributes
    -----------------
    indexed : list
        A list of booleans indicating if each argument within the event is
        indexed.
    """

    __slots__ = ("indexed",)
    _id = "event"
    _member_of = "log"

    def __init__(self, name: str = None, arguments=None, indexed=None):
        super().__init__(name, arguments, len(arguments or []), None)
        self.indexed = indexed

    def __eq__(self, other):
        return (
            isinstance(other, Event) and
            self.name == other.name and
            self.arguments == other.arguments
        )

    @classmethod
    def from_ann_assign(cls, name, annotation: vy_ast.VyperNode, value, is_public):
        if value:
            raise EventDeclarationException("Cannot assign a value to an event", value)

        arguments = OrderedDict()
        indexed = []
        validate_call_args(annotation, 1)
        if not isinstance(annotation.args[0], vy_ast.Dict):
            raise StructureException("Invalid event declaration syntax", annotation.args[0])
        for key, value in zip(annotation.args[0].keys, annotation.args[0].values):
            if isinstance(value, vy_ast.Call) and value.get('func.id') == "indexed":
                validate_call_args(value, 1)
                indexed.append(True)
                value = value.args[0]
            else:
                indexed.append(False)
            arguments[key] = get_type_from_annotation(value)
        return cls(name, arguments, indexed)
