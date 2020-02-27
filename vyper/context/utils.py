from typing import (
    Optional,
    Set,
    Union,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.types import (
    bases,
)
from vyper.exceptions import (
    CompilerPanic,
    StructureException,
)


class VyperNodeVisitorBase:

    ignored_types = ()
    scope_name = ""

    def visit(self, node):
        if isinstance(node, self.ignored_types):
            return
        visitor_fn = getattr(self, f'visit_{node.ast_type}', None)
        if visitor_fn is None:
            raise StructureException(
                f"Unsupported syntax for {self.scope_name} namespace: {node.ast_type}", node
            )
        visitor_fn(node)


def check_call_args(
    node: vy_ast.VyperNode,
    argcount: Union[int, tuple],
    kwargs: Optional[Set] = None
) -> None:

    if not isinstance(node, vy_ast.Call):
        raise StructureException("Expected Call", node)
    if not isinstance(argcount, (int, tuple)):
        raise CompilerPanic(f"Invalid type for argcount: {type(argcount).__name__}")

    if isinstance(argcount, int) and len(node.args) != argcount:
        raise StructureException(
            f"Invalid argument count: expected {argcount}, got {len(node.args)}", node
        )
    elif isinstance(argcount, tuple) and not argcount[0] <= len(node.args) <= argcount[1]:
        raise StructureException(
            f"Invalid argument count: expected between "
            f"{argcount[0]} and {argcount[1]}, got {len(node.args)}",
            node
        )

    if kwargs is None and node.keywords:
        raise StructureException("Keyword arguments are not accepted here", node.keywords[0])
    for key in node.keywords:
        if key.arg is None:
            raise StructureException("Use of **kwargs is not supported", key.value)
        if key.arg not in kwargs:
            raise


def get_leftmost_id(node: vy_ast.VyperNode) -> str:
    return next(i.id for i in node.get_all_children({'ast_type': 'Name'}, True))


def get_index_value(namespace, node):
    if not isinstance(node, vy_ast.Index):
        raise

    if isinstance(node.value, vy_ast.Int):
        return node.value.value

    if isinstance(node.value, vy_ast.Name):
        slice_name = node.value.id
        length = namespace[slice_name]

        if not length.is_constant:
            raise StructureException("Slice must be an integer or constant", node)

        typ = length.type
        if not isinstance(typ, bases.IntegerType):
            raise StructureException(f"Invalid type for Slice: '{typ}'", node)
        if typ.unit:
            raise StructureException(f"Slice value must be unitless, not '{typ.unit}'", node)
        return length.literal_value()

    raise StructureException("Slice must be an integer or constant", node)
