from vyper import ast as vy_ast
from vyper.exceptions import VyperException


def expr_contains_unbounded_sequence(node: vy_ast.VyperNode) -> bool:
    if isinstance(node, (vy_ast.Tuple, vy_ast.List)):
        return any(expr_contains_unbounded_sequence(item) for item in node.elements)

    # Keep these imports local: user-defined types need this predicate while
    # analysis.utils itself imports the user type module during initialization.
    from vyper.semantics.analysis.utils import get_exact_type_from_node
    from vyper.semantics.types.infinity import type_contains_unbounded_sequence

    try:
        return type_contains_unbounded_sequence(get_exact_type_from_node(node))
    except VyperException:
        return False
