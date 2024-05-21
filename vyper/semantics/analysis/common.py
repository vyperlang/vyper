from typing import Tuple

from vyper.exceptions import StructureException, tag_exceptions


class VyperNodeVisitorBase:
    ignored_types: Tuple = ()
    scope_name = ""

    def visit(self, node, *args):
        if isinstance(node, self.ignored_types):
            return

        # iterate over the MRO until we find a matching visitor function
        # this lets us use a single function to broadly target several
        # node types with a shared parent
        for class_ in node.__class__.mro():
            ast_type = class_.__name__

            with tag_exceptions(node):
                visitor_fn = getattr(self, f"visit_{ast_type}", None)
                if visitor_fn:
                    return visitor_fn(node, *args)

        node_type = type(node).__name__
        raise StructureException(
            f"Unsupported syntax for {self.scope_name} namespace: {node_type}", node
        )
