import copy

from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic
from vyper.semantics.types.function import ContractFunctionT


# CMC 2024-02-20 NOTE: it may be beneficial to remove this function; it
# causes correctness and performance problems because of copying and mutating
# the AST. we could handle getter generation during code generation.
def generate_public_variable_getters(vyper_module: vy_ast.Module) -> None:
    """
    Create getter functions for public variables.

    Arguments
    ---------
    vyper_module : Module
        Top-level Vyper AST node.
    """

    for node in vyper_module.get_children(vy_ast.VariableDecl, {"is_public": True}):
        funcname = node.target.id
        input_types, return_type = node._metadata["type"].getter_signature

        input_nodes = []

        # use the annotation node to build the input args and return type
        annotation = copy.copy(node.annotation)

        return_expr: vy_ast.ExprNode
        # constants just return a value
        if node.is_constant:
            return_expr = node.value
        elif node.is_immutable:
            return_expr = vy_ast.Name(id=funcname)  # type: ignore
        else:
            # the base return statement is an `Attribute` node, e.g.
            # `self.<var_name>`. for each input type we wrap it in a
            # `Subscript` to access a specific member
            return_expr = vy_ast.Attribute(value=vy_ast.Name(id="self"), attr=funcname)

        for i, type_ in enumerate(input_types):
            if not isinstance(annotation, vy_ast.Subscript):
                # if we get here something has failed in type checking
                raise CompilerPanic("Mismatch between node and input type while building getter")
            if annotation.value.get("id") == "HashMap":  # type: ignore
                # for a HashMap, split the key/value types and use the key
                # type as the next arg
                arg, annotation = annotation.slice.elements  # type: ignore
            elif annotation.value.get("id") == "DynArray":
                arg = vy_ast.Name(id=type_._id)
                annotation = annotation.slice.elements[0]  # type: ignore
            else:
                # for other types, build an input arg node from the expected
                # type and remove the outer `Subscript` from the annotation
                arg = vy_ast.Name(id=type_._id)
                annotation = annotation.value
            input_nodes.append(vy_ast.arg(arg=f"arg{i}", annotation=arg))

            # wrap the return expression in a `Subscript`
            return_expr = vy_ast.Subscript(value=return_expr, slice=vy_ast.Name(id=f"arg{i}"))

        # after iterating the input types, the remaining annotation node is our return type
        return_annotation = copy.copy(annotation)

        decorators = [vy_ast.Name(id="external"), vy_ast.Name(id="view")]
        settings = node.module_node.settings
        if settings.nonreentrancy_by_default:
            # immutable and constant variables can't change, and thus
            # can't lead to read-only-reentrancy
            if node.is_reentrant or node.is_constant or node.is_immutable:
                decorators.append(vy_ast.Name(id="reentrant"))

        # join everything together as a new `FunctionDef` node
        expanded = vy_ast.FunctionDef(
            name=funcname,
            args=vy_ast.arguments(args=input_nodes, defaults=[]),
            body=[vy_ast.Return(value=return_expr)],
            decorator_list=decorators,
            returns=return_annotation,
        )

        # set some pointers for error messages
        expanded._original_node = node
        expanded.set_parent(node.parent)

        func_type = ContractFunctionT.from_FunctionDef(expanded)
        expanded._metadata["func_type"] = func_type

        # update pointers
        node._expanded_getter = expanded
