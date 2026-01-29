from typing import Generic, Tuple, TypeVar

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


Res = TypeVar("Res")


class NodeAccumulator(Generic[Res]):
    """
    Utility to traverse nodes and accumulate some value over them.
    To use, create a sub-class.
    Since all the logic is in classmethods, there can be no mutable state.
    Instead encapsulate immutable state in the `acc` parameter.

    Add `visit_<ast_type>` methods (ex: `visit_Call`) to handle specific nodes.

    Override `visit` for logic that affects all nodes, do not forget to call `super.visit` !

    By default, it will crash on unhandled nodes, to instead recurse on unhandled nodes add a:
    ```
    def visit_VyperNode(self, node, ...):
        return self.dispatch(node, ...)
    ```

    Note:
    Ideally, there would be a way to add a default value to the methods
    Sadly this either requires a sentinel value and all the logic that requires
    Or a `@classmethod @property`, which
    [were removed in python 3.11](https://docs.python.org/3.11/library/functions.html#classmethod)
    """

    scope_name = ""

    def __new__(cls):
        raise TypeError("`NodeAccumulator`s cannot be instantiated")

    @classmethod
    def visit(cls, node, acc: Res) -> Res:
        # iterate over the MRO until we find a matching visitor function
        # this lets us use a single function to broadly target several
        # node types with a shared parent
        for class_ in node.__class__.mro():
            ast_type = class_.__name__

            with tag_exceptions(node):
                visitor_fn = getattr(cls, f"visit_{ast_type}", None)
                if visitor_fn:
                    return visitor_fn(node, acc)

        node_type = type(node).__name__
        raise StructureException(
            f"Unsupported syntax for {cls.scope_name} namespace: {node_type}", node
        )

    @classmethod
    def visit_block(cls, block, acc: Res) -> Res:
        for node in block:
            acc = cls.visit(node, acc)

        return acc

    # Call this to instead accumulate over the children
    @classmethod
    def dispatch(cls, node, acc: Res) -> Res:
        return cls.visit_block(node._children, acc)
