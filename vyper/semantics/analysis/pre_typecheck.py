from vyper import ast as vy_ast
from vyper.exceptions import UnfoldableNode
from vyper.semantics.analysis.common import VyperNodeVisitorBase


def get_constants(node: vy_ast.Module) -> dict:
    constants = {}
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

            prefold(c, constants)

            val = c._metadata.get("folded_value")

            # note that if a constant is redefined, its value will be overwritten,
            # but it is okay because the syntax error is handled downstream
            if val is not None:
                self.constants[name] = val
                derived_nodes += 1
                const_var_decls.remove(c)

        if not derived_nodes:
            break

    return constants


def pre_typecheck(node: vy_ast.Module):
    constants = get_constants(node)
    
    for n in node.get_descendants(reverse=True):
        if isinstance(n, vy_ast.VariableDecl):
            continue
        
        prefold(n, constants)


def prefold(node: vy_ast.VyperNode, constants: dict) -> None:
    print("prefolding")
    if isinstance(node, vy_ast.BinOp):
        node._metadata["folded_value"] = node.prefold()

    if isinstance(node, vy_ast.UnaryOp):
        node._metadata["folded_value"] = node.prefold()
    
    if isinstance(node, vy_ast.Constant):
        node._metadata["folded_value"] = node