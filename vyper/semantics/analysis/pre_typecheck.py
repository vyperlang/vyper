from vyper import ast as vy_ast
from vyper.exceptions import UnfoldableNode, VyperException


def get_constants(node: vy_ast.Module) -> dict:
    constants: dict[str, vy_ast.VyperNode] = {}
    module_nodes = node.body.copy()
    const_var_decls = [
        n for n in module_nodes if isinstance(n, vy_ast.VariableDecl) and n.is_constant
    ]

    while const_var_decls:
        derived_nodes = 0

        for c in const_var_decls:
            name = c.get("target.id")
            # Handle syntax errors downstream
            if c.value is None:
                continue

            for n in c.value.get_descendants(include_self=True, reverse=True):
                prefold(n, constants)

            val = c.value._metadata.get("folded_value")

            # note that if a constant is redefined, its value will be overwritten,
            # but it is okay because the syntax error is handled downstream
            if val is not None:
                constants[name] = val
                derived_nodes += 1
                const_var_decls.remove(c)

        if not derived_nodes:
            break

    return constants


def pre_typecheck(node: vy_ast.Module) -> None:
    constants = get_constants(node)

    for n in node.get_descendants(reverse=True):
        if isinstance(n, vy_ast.VariableDecl):
            continue

        prefold(n, constants)


def prefold(node: vy_ast.VyperNode, constants: dict[str, vy_ast.VyperNode]):
    if isinstance(node, vy_ast.Name):
        var_name = node.id
        if var_name in constants:
            node._metadata["folded_value"] = constants[var_name]
            return

    if isinstance(node, vy_ast.Call):
        if isinstance(node.func, vy_ast.Name):
            from vyper.builtins.functions import DISPATCH_TABLE

            func_name = node.func.id

            call_type = DISPATCH_TABLE.get(func_name)
            if call_type and hasattr(call_type, "fold"):
                try:
                    node._metadata["folded_value"] = call_type.fold(node)
                    return
                except (UnfoldableNode, VyperException):
                    pass

    if getattr(node, "_is_prefoldable", None):
        try:
            # call `get_folded_value`` for its side effects
            node.get_folded_value()
        except (UnfoldableNode, VyperException):
            pass
