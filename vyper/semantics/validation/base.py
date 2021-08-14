from typing import Tuple

from vyper.exceptions import StructureException


class VyperNodeVisitorBase:

    ignored_types: Tuple = ()
    scope_name = ""

    def visit(self, node):
        if isinstance(node, self.ignored_types):
            return
        node_type = type(node).__name__
        visitor_fn = getattr(self, f"visit_{node_type}", None)
        if visitor_fn is None:
            raise StructureException(
                f"Unsupported syntax for {self.scope_name} namespace: {node_type}", node,
            )
        visitor_fn(node)
