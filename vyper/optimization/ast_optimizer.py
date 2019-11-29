import vyper.ast as vyper_ast


class FoldConstants(vyper_ast.NodeTransformer):
    """
    Series of rewrites rules that attempt to reduce arithmatic expressions between 1
    or more literals down to a literal itself, by executing the expressions at compile
    time (assuming EVM execution).

    All node visitors either return themself or a literal (vyper_ast.Num)
    """
    def visit_UnaryOp(self, node):
        if not isinstance(node.operand, vyper_ast.Num):
            # Recurse deeply to reduce complex literal expressions
            node.operand = self.visit(node.operand)

        # TODO: This should actually be USub... but we're directly using Python's AST class
        #       instead of fully converting it to our own
        if isinstance(node.op, vyper_ast.USub) and isinstance(node.operand, vyper_ast.Num):
            new_node = node.operand
            new_node.n = -new_node.n
            new_node.col_offset = node.col_offset
            return new_node
        return node


# TODO: Use cachetools?
def get_optimizations():
    import inspect
    import sys
    optimizations = dict()
    for name, obj in inspect.getmembers(sys.modules[__name__]):
        if inspect.isclass(obj):
            optimizations[name] = obj
    return optimizations


AVAILABLE_OPTIMIZATIONS = set(get_optimizations().keys())


def optimize(node, selected=AVAILABLE_OPTIMIZATIONS):
    """
    Visit the given node and apply the selected optimizations
    """
    optimizations = [opt() for name, opt in get_optimizations().items() if name in selected]
    for opt in optimizations:
        node = opt.visit(node)
    return node
