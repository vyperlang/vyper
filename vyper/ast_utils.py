import ast as python_ast
from typing import (
    Generator,
)

import asttokens

import vyper.ast as vyper_ast
from vyper.exceptions import (
    CompilerPanic,
    ParserException,
    SyntaxException,
)
from vyper.parser.parser_utils import (
    annotate_ast,
)
from vyper.parser.pre_parser import (
    pre_parse,
)
from vyper.utils import (
    iterable_cast,
)

DICT_AST_SKIPLIST = ('source_code', )


@iterable_cast(list)
def _build_vyper_ast_list(source_code: str, node: list, source_id: int) -> Generator:
    for n in node:
        yield parse_python_ast(
            source_code=source_code,
            node=n,
            source_id=source_id,
        )


@iterable_cast(dict)
def _build_vyper_ast_init_kwargs(
    source_code: str,
    node: python_ast.AST,
    vyper_class: vyper_ast.VyperNode,
    source_id: int,
) -> Generator:
    start = node.first_token.start if hasattr(node, 'first_token') else (None, None)  # type: ignore
    yield ('col_offset', start[1])
    yield ('lineno', start[0])
    yield ('node_id', node.node_id)  # type: ignore
    yield ('source_code', source_code)

    end = node.last_token.end if hasattr(node, 'last_token') else (None, None)  # type: ignore
    yield ('end_lineno', end[0])
    yield ('end_col_offset', end[1])
    if hasattr(node, 'last_token'):
        start_pos = node.first_token.startpos  # type: ignore
        end_pos = node.last_token.endpos  # type: ignore
        yield ('src', f"{start_pos}:{end_pos-start_pos}:{source_id}")

    if isinstance(node, python_ast.ClassDef):
        yield ('class_type', node.class_type)  # type: ignore

    for field_name in vyper_class.get_slots():
        if hasattr(node, field_name):
            yield (
                field_name,
                parse_python_ast(
                    source_code=source_code,
                    node=getattr(node, field_name),
                    source_id=source_id
                )
            )


def parse_python_ast(source_code: str,
                     node: python_ast.AST,
                     source_id: int = 0) -> vyper_ast.VyperNode:
    if isinstance(node, list):
        return _build_vyper_ast_list(source_code, node, source_id)
    if not isinstance(node, python_ast.AST):
        return node

    class_name = node.__class__.__name__
    if isinstance(node, python_ast.Constant):
        if node.value is None or isinstance(node.value, bool):
            class_name = "NameConstant"
        elif isinstance(node.value, (int, float)):
            class_name = "Num"
        elif isinstance(node.value, str):
            class_name = "Str"
        elif isinstance(node.value, bytes):
            class_name = "Bytes"
    if not hasattr(vyper_ast, class_name):
        raise SyntaxException(f'Invalid syntax (unsupported "{class_name}" Python AST node).', node)

    vyper_class = getattr(vyper_ast, class_name)
    for field_name in vyper_class.only_empty_fields:
        if field_name in node._fields and getattr(node, field_name, None):
            raise SyntaxException(
                f'Invalid Vyper Syntax. "{field_name}" is an unsupported attribute field '
                f'on Python AST "{class_name}" class.',
                field_name
            )

    init_kwargs = _build_vyper_ast_init_kwargs(source_code, node, vyper_class, source_id)
    return vyper_class(**init_kwargs)


def parse_to_ast(source_code: str, source_id: int = 0) -> list:
    if '\x00' in source_code:
        raise ParserException('No null bytes (\\x00) allowed in the source code.')
    class_types, reformatted_code = pre_parse(source_code)
    py_ast = python_ast.parse(reformatted_code)
    annotate_ast(py_ast, source_code, class_types)
    asttokens.ASTTokens(source_code, tree=py_ast)
    # Convert to Vyper AST.
    vyper_ast = parse_python_ast(
        source_code=source_code,
        node=py_ast,
        source_id=source_id,
    )
    return vyper_ast.body  # type: ignore


@iterable_cast(list)
def _ast_to_list(node: list) -> Generator:
    for x in node:
        yield ast_to_dict(x)


@iterable_cast(dict)
def _ast_to_dict(node: vyper_ast.VyperNode) -> Generator:
    for f in node.get_slots():
        if f not in DICT_AST_SKIPLIST:
            yield (f, ast_to_dict(getattr(node, f, None)))
    yield ('ast_type', node.__class__.__name__)


def ast_to_dict(node: vyper_ast.VyperNode) -> dict:
    if isinstance(node, vyper_ast.VyperNode):
        return _ast_to_dict(node)
    elif isinstance(node, list):
        return _ast_to_list(node)
    elif node is None or isinstance(node, (str, int)):
        return node
    else:
        raise CompilerPanic('Unknown vyper AST node provided.')


def dict_to_ast(ast_struct: dict) -> vyper_ast.VyperNode:
    if isinstance(ast_struct, dict) and 'ast_type' in ast_struct:
        vyper_class = getattr(vyper_ast, ast_struct['ast_type'])
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
    elif ast_struct is None or isinstance(ast_struct, (str, int)):
        return ast_struct
    else:
        raise CompilerPanic('Unknown ast_struct provided.')


def to_python_ast(vyper_ast_node: vyper_ast.VyperNode) -> python_ast.AST:
    if isinstance(vyper_ast_node, list):
        return [
            to_python_ast(n)
            for n in vyper_ast_node
        ]
    elif isinstance(vyper_ast_node, vyper_ast.VyperNode):
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


def ast_to_string(vyper_ast_node: vyper_ast.VyperNode) -> str:
    py_ast_node = to_python_ast(vyper_ast_node)
    return python_ast.dump(
        python_ast.Module(
            body=py_ast_node
        )
    )
