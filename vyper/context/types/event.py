from collections import OrderedDict
from typing import List

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.context.types.utils import get_type_from_annotation
from vyper.context.validation.utils import validate_expected_type
from vyper.exceptions import StructureException

# NOTE: This implementation isn't as polished as it could be, because it will be
# replaced with a new struct-style syntax prior to the next release.


class Event:
    """
    Event type.

    Event are special types that exist as members of the builtin `log` object.

    Attributes
    ----------
    indexed : list
        A list of booleans indicating if each argument within the event is
        indexed.
    """

    _id = "event"
    _member_of = "log"

    def __init__(self, arguments: OrderedDict, indexed: List) -> None:
        self.arguments = arguments
        self.indexed = indexed

    @classmethod
    def from_annotation(
        cls, node: vy_ast.Call, is_constant: bool = False, is_public: bool = False
    ) -> "Event":
        arguments = OrderedDict()
        indexed = []
        validate_call_args(node, 1)
        if not isinstance(node.args[0], vy_ast.Dict):
            raise StructureException("Invalid event declaration syntax", node.args[0])
        for key, value in zip(node.args[0].keys, node.args[0].values):
            if isinstance(value, vy_ast.Call) and value.get("func.id") == "indexed":
                validate_call_args(value, 1)
                indexed.append(True)
                value = value.args[0]
            else:
                indexed.append(False)
            arguments[key] = get_type_from_annotation(value)
        return cls(arguments, indexed)

    def fetch_call_return(self, node: vy_ast.Call) -> None:
        validate_call_args(node, len(self.arguments))
        for arg, expected in zip(node.args, self.arguments.values()):
            validate_expected_type(arg, expected)
