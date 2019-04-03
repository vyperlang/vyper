import ast as python_ast

import vyper.ast as vyper_ast
from vyper.exceptions import (
    ParserException,
    SyntaxException,
)
from vyper.parser.parser_utils import (
    annotate_and_optimize_ast,
)
from vyper.parser.pre_parser import (
    pre_parse,
)


def parse_python_ast(source_code, node):
    if isinstance(node, list):
        o = []
        for n in node:
            o.append(
                parse_python_ast(
                    source_code=source_code,
                    node=n,
                )
            )
        return o
    elif isinstance(node, python_ast.AST):
        class_name = node.__class__.__name__
        if hasattr(vyper_ast, class_name):
            vyper_class = getattr(vyper_ast, class_name)
            init_kwargs = {
                'col_offset': getattr(node, 'col_offset', None),
                'lineno': getattr(node, 'lineno', None),
                'node_id': node.node_id
            }
            if isinstance(node, python_ast.ClassDef):
                init_kwargs['class_type'] = node.class_type
            for field_name in node._fields:
                val = getattr(node, field_name)
                if field_name in vyper_class.ignored_fields:
                    continue
                elif val and field_name in vyper_class.only_empty_fields:
                    raise SyntaxException(
                        f'"{field_name}" is an unsupported attribute field '
                        f'on Python AST "{class_name}" class.', node
                    )
                else:
                    init_kwargs[field_name] = parse_python_ast(
                        source_code=source_code,
                        node=val,
                    )
            return vyper_class(**init_kwargs)
        else:
            raise SyntaxException(
                f'Invalid syntax (unsupported "{class_name}" Python AST node).', node
            )
    else:
        return node


def parse_to_ast(source_code):
    class_types, reformatted_code = pre_parse(source_code)
    if '\x00' in reformatted_code:
        raise ParserException('No null bytes (\\x00) allowed in the source code.')
    py_ast = python_ast.parse(reformatted_code)
    annotate_and_optimize_ast(py_ast, source_code, class_types)
    # Convert to Vyper AST.
    vyper_ast = parse_python_ast(
        source_code=source_code,
        node=py_ast,
    )
    return vyper_ast.body


def ast_to_dict(node):
    skip_list = ('source_code', )
    if isinstance(node, vyper_ast.VyperNode):
        o = {
            f: ast_to_dict(getattr(node, f))
            for f in node.get_slots()
            if f not in skip_list
        }
        o.update({'ast_type': node.__class__.__name__})
        return o
    elif isinstance(node, list):
        return [
            ast_to_dict(x)
            for x in node
        ]
    else:
        return node
