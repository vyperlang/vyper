import ast as python_ast
from typing import (
    Generator,
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
from vyper.utils import (
    iterable_cast,
)

DICT_AST_SKIPLIST = ('source_code', )


def parse_to_ast(source_code: str, source_id: int = 0) -> list:
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
    return vy_ast.get_node(py_ast).body  # type: ignore


@iterable_cast(list)
def _ast_to_list(node: list) -> Generator:
    for x in node:
        yield ast_to_dict(x)


@iterable_cast(dict)
def _ast_to_dict(node: vy_ast.VyperNode) -> Generator:
    for f in node.get_slots():
        if f not in DICT_AST_SKIPLIST:
            yield (f, ast_to_dict(getattr(node, f, None)))
    yield ('ast_type', node.__class__.__name__)


def ast_to_dict(node: vy_ast.VyperNode) -> dict:
    if isinstance(node, vy_ast.VyperNode):
        return _ast_to_dict(node)
    elif isinstance(node, list):
        return _ast_to_list(node)
    elif node is None or isinstance(node, (str, int, bytes, float)):
        return node
    else:
        raise CompilerPanic(f'Unknown vyper AST node provided: "{type(node)}".')


def dict_to_ast(ast_struct: dict) -> vy_ast.VyperNode:
    if isinstance(ast_struct, dict):
        return vy_ast.get_node(ast_struct)
    if isinstance(ast_struct, list):
        return [vy_ast.get_node(i) for i in ast_struct]
    raise CompilerPanic(f'Unknown ast_struct provided: "{type(ast_struct)}".')


def to_python_ast(vyper_ast_node: vy_ast.VyperNode) -> python_ast.AST:
    if isinstance(vyper_ast_node, list):
        return [
            to_python_ast(n)
            for n in vyper_ast_node
        ]
    elif isinstance(vyper_ast_node, vy_ast.VyperNode):
        class_name = vyper_ast_node.__class__.__name__
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
    return python_ast.dump(
        python_ast.Module(
            body=py_ast_node
        )
    )
