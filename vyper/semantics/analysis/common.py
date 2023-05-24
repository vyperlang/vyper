from typing import Tuple

from vyper.exceptions import StructureException


class VyperNodeVisitorBase:
    ignored_types: Tuple = ()
    scope_name = ""

    def visit(self, node, *args):
        if isinstance(node, self.ignored_types):
            return
        node_type = type(node).__name__
        visitor_fn = getattr(self, f"visit_{node_type}", None)
        if visitor_fn:
            visitor_fn(node, *args)
            return

        # iterate over the MRO until we find a matching visitor function
        # this lets us use a single function to broadly target several
        # node types with a shared parent
        for class_ in node.__class__.mro():
            ast_type = class_.__name__
            visitor_fn = getattr(self, f"visit_{ast_type}", None)
            if visitor_fn:
                visitor_fn(node, *args)
                return

        raise StructureException(
            f"Unsupported syntax for {self.scope_name} namespace: {node_type}", node
        )
        
