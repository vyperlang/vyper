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
    SyntaxException,
)
from vyper.utils import (
    iterable_cast,
)

DICT_AST_SKIPLIST = ('source_code', )


@iterable_cast(list)
def _build_vyper_ast_list(source_code: str, node: list) -> Generator:
    for n in node:
        yield parse_python_ast(
            source_code=source_code,
            node=n,
        )


@iterable_cast(dict)
def _build_vyper_ast_init_kwargs(
    source_code: str,
    node: python_ast.AST,
    vyper_class: vy_ast.VyperNode,
) -> Generator:
    yield ('col_offset', node.col_offset)
    yield ('lineno', node.lineno)
    yield ('node_id', node.node_id)  # type: ignore
    yield ('source_code', source_code)

    yield ('end_lineno', node.end_lineno)
    yield ('end_col_offset', node.end_col_offset)
    if hasattr(node, 'src'):
        yield ('src', node.src)  # type: ignore

    yield ('ast_type', node.ast_type)  # type: ignore
    if isinstance(node, python_ast.ClassDef):
        yield ('class_type', node.class_type)  # type: ignore

    for field_name in vyper_class.get_slots():
        if field_name not in vy_ast.BASE_NODE_ATTRIBUTES and hasattr(node, field_name):
            yield (
                field_name,
                parse_python_ast(
                    source_code=source_code,
                    node=getattr(node, field_name),
                )
            )


def parse_python_ast(source_code: str,
                     node: python_ast.AST) -> vy_ast.VyperNode:
    if isinstance(node, list):
        return _build_vyper_ast_list(source_code, node)
    if not isinstance(node, python_ast.AST):
        return node

    class_name = node.ast_type  # type: ignore
    if not hasattr(vy_ast, class_name):
        raise SyntaxException(f'Invalid syntax (unsupported "{class_name}" Python AST node).', node)

    vyper_class = getattr(vy_ast, class_name)
    for field_name in vyper_class.only_empty_fields:
        if field_name in node._fields and getattr(node, field_name, None):
            raise SyntaxException(
                f'Invalid Vyper Syntax. "{field_name}" is an unsupported attribute field '
                f'on Python AST "{class_name}" class.',
                field_name
            )

    init_kwargs = _build_vyper_ast_init_kwargs(source_code, node, vyper_class)
    return vyper_class(**init_kwargs)


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
    vy_ast = parse_python_ast(
        source_code=source_code,
        node=py_ast,
    )
    return vy_ast.body  # type: ignore


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
    if isinstance(ast_struct, dict) and 'ast_type' in ast_struct:
        vyper_class = getattr(vy_ast, ast_struct['ast_type'])
        klass = vyper_class(**{
            k: dict_to_ast(v)
            for k, v in ast_struct.items()
            if k in vyper_class.get_slots()
        })
        return klass
    elif isinstance(ast_struct, list):
        return [
            dict_to_ast(x)
            for x in ast_struct
        ]
    elif ast_struct is None or isinstance(ast_struct, (str, int, bytes, float)):
        return ast_struct
    else:
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
