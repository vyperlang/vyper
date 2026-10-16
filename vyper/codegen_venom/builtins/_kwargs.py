"""
Keyword-argument helpers shared by the builtin lowering modules.
"""

from __future__ import annotations

from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic


def get_kwarg_value(node: vy_ast.Call, kwarg_name: str, default=None):
    """Extract a keyword argument value from a Call node."""
    for kw in node.keywords:
        if kw.arg == kwarg_name:
            return kw.value
    return default


def get_bool_kwarg(node: vy_ast.Call, kwarg_name: str, default: bool) -> bool:
    """
    Extract a literal boolean keyword argument.

    For kwargs declared as `KwargSettings(BoolT(), ..., require_literal=True)`.
    The frontend only accepts a constant bool expression there, so the
    reduced node is always a `NameConstant`.
    """
    kw_node = get_kwarg_value(node, kwarg_name)
    if kw_node is None:
        return default
    kw_node = kw_node.reduced()
    if isinstance(kw_node, vy_ast.NameConstant) and isinstance(kw_node.value, bool):
        return kw_node.value
    raise CompilerPanic(f"unfoldable boolean kwarg: {kwarg_name}", kw_node)
