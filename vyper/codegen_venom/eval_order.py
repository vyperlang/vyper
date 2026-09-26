from __future__ import annotations

from collections.abc import Iterable

from vyper import ast as vy_ast
from vyper.builtins._signatures import BuiltinFunctionT
from vyper.exceptions import UnfoldableNode
from vyper.semantics.types.function import ContractFunctionT, MemberFunctionT

_STATEFUL_BUILTIN_IDS = {
    "raw_call",
    "send",
    "raw_create",
    "create_minimal_proxy_to",
    "create_copy_of",
    "create_from_blueprint",
    "selfdestruct",
}


def _raw_call_is_static(node: vy_ast.Call) -> bool:
    for kw in node.keywords:
        if kw.arg != "is_static_call":
            continue
        try:
            return bool(kw.value.get_folded_value().value)
        except (AttributeError, KeyError, UnfoldableNode):
            return False
    return False


def _call_can_mutate(node: vy_ast.Call) -> bool:
    if node.is_extcall:
        return True
    if node.is_staticcall:
        return False

    func_t = node.func._metadata.get("type")
    if isinstance(func_t, MemberFunctionT):
        return isinstance(node.func, vy_ast.Attribute) and node.func.attr in ("append", "pop")

    if isinstance(func_t, ContractFunctionT):
        return func_t.is_modifying

    if isinstance(func_t, BuiltinFunctionT):
        if func_t._id == "raw_call":
            return not _raw_call_is_static(node)
        if func_t._id in _STATEFUL_BUILTIN_IDS:
            return True
        return func_t.is_modifying

    return False


def expression_can_mutate_memory_or_storage(node: vy_ast.VyperNode) -> bool:
    for child in node.get_descendants(include_self=True):
        if isinstance(child, vy_ast.ExtCall):
            return True
        if isinstance(child, vy_ast.Call) and _call_can_mutate(child):
            return True
    return False


def later_expressions_can_mutate_memory_or_storage(nodes: Iterable[vy_ast.VyperNode]) -> bool:
    return any(expression_can_mutate_memory_or_storage(node) for node in nodes)
