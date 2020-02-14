import ast as python_ast
from typing import (
    Dict,
    List,
    Union,
)

from vyper.ast import (
    nodes as vy_ast,
)
from vyper.ast.annotation import (
    annotate_python_ast,
)
from vyper.ast.pre_parser import (
    pre_parse,
)
from vyper.exceptions import (
    CompilerPanic,
    ParserException,
    PythonSyntaxException,
)


def parse_to_ast(source_code: str, source_id: int = 0) -> vy_ast.Module:
    """
    Parses a vyper source string and generates basic vyper AST nodes.

    Parameters
    ----------
    source_code : str
        The vyper source code to parse.
    source_id : int, optional
        Source id to use in the .src member of each node.

    Returns
    -------
    list
        Untyped, unoptimized vyper AST nodes.
    """
    if '\x00' in source_code:
        raise ParserException('No null bytes (\\x00) allowed in the source code.')
    class_types, reformatted_code = pre_parse(source_code)
    try:
        py_ast = python_ast.parse(reformatted_code)
    except SyntaxError as e:
        # TODO: Ensure 1-to-1 match of source_code:reformatted_code SyntaxErrors
        raise PythonSyntaxException(e, source_code) from e
    annotate_python_ast(py_ast, source_code, class_types, source_id)

    # Convert to Vyper AST.
    return vy_ast.get_node(py_ast)  # type: ignore


def ast_to_dict(ast_struct: Union[vy_ast.VyperNode, List]) -> Union[Dict, List]:
    """
    Converts a vyper AST node, or list of nodes, into a dictionary suitable for
    output to the user.
    """
    if isinstance(ast_struct, vy_ast.VyperNode):
        return ast_struct.to_dict()
    elif isinstance(ast_struct, list):
        return [i.to_dict() for i in ast_struct]
    else:
        raise CompilerPanic(f'Unknown vyper AST node provided: "{type(ast_struct)}".')


def dict_to_ast(ast_struct: Union[Dict, List]) -> Union[vy_ast.VyperNode, List]:
    """
    Converts an AST dict, or list of dicts, into vyper AST node objects.
    """
    if isinstance(ast_struct, dict):
        return vy_ast.get_node(ast_struct)
    if isinstance(ast_struct, list):
        return [vy_ast.get_node(i) for i in ast_struct]
    raise CompilerPanic(f'Unknown ast_struct provided: "{type(ast_struct)}".')


def to_python_ast(vyper_ast_node: vy_ast.VyperNode) -> python_ast.AST:
    """
    Converts a vyper AST node object into to a python AST node.
    """
    if isinstance(vyper_ast_node, list):
        return [
            to_python_ast(n)
            for n in vyper_ast_node
        ]
    elif isinstance(vyper_ast_node, vy_ast.VyperNode):

        class_name = vyper_ast_node.ast_type  # type: ignore
        if hasattr(vyper_ast_node, "_python_ast_type"):
            class_name = vyper_ast_node._python_ast_type  # type: ignore

        if hasattr(python_ast, class_name):
            py_klass = getattr(python_ast, class_name)
            return py_klass(**{
                k: to_python_ast(
                    getattr(vyper_ast_node, k, None)
                )
                for k in vyper_ast_node.get_slots()
            })
        else:
            raise CompilerPanic(f'Unknown vyper AST class "{class_name}" provided.')
    else:
        return vyper_ast_node


def ast_to_string(vyper_ast_node: vy_ast.VyperNode) -> str:
    py_ast_node = to_python_ast(vyper_ast_node)
    return python_ast.dump(py_ast_node)
