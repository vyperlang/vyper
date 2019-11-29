from typing import (
    Dict,
    Union,
)

import vyper.ast as vyper_ast


# TODO: Use cachetools?
def get_optimizations() -> Dict[str, vyper_ast.NodeTransformer]:
    import inspect
    import sys
    optimizations = dict()
    for name, obj in inspect.getmembers(sys.modules[__name__]):
        if inspect.isclass(obj):
            optimizations[name] = obj
    return optimizations


AVAILABLE_OPTIMIZATIONS = set(get_optimizations().keys())


def optimize(node: vyper_ast.VyperNode, selected=AVAILABLE_OPTIMIZATIONS) -> vyper_ast.VyperNode:
    """
    Visit the given node and apply the selected optimizations
    """
    optimizations = [opt() for name, opt in get_optimizations().items() if name in selected]
    for opt in optimizations:
        node = opt.visit(node)
    return node
