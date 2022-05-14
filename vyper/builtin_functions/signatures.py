import functools

from vyper.ast import nodes as vy_ast
from vyper.codegen.expr import Expr
from vyper.codegen.types.convert import new_type_to_old_type
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import (
    AbstractNumericDefinition,
    ArrayDefinition,
    BoolDefinition,
    BytesArrayDefinition,
    StringDefinition,
)
from vyper.semantics.types.bases import BaseTypeDefinition


class Optional(object):
    def __init__(self, typ, default, require_literal=False):
        self.typ = typ
        self.default = default
        self.require_literal = require_literal


class TypeTypeDefinition:
    def __init__(self, typedef):
        self.typedef = typedef

    def __repr__(self):
        return f"type({self.typedef})"


def _process_optional_literal_value(optional_obj, kwarg_node):
    # Returns the literal value from the corresponding AST node for a kwarg
    if not isinstance(kwarg_node, vy_ast.Constant):
        raise TypeMismatch("Value for kwarg must be a literal")

    if isinstance(optional_obj.typ, BoolDefinition):
        return kwarg_node.value
    elif isinstance(optional_obj.typ, AbstractNumericDefinition):
        return kwarg_node.n

    raise CompilerPanic("Unexpected type for optional kwarg")


def process_arg(arg, expected_arg_type, context):
    if isinstance(expected_arg_type, (BytesArrayDefinition, StringDefinition, ArrayDefinition)):
        return Expr(arg, context).ir_node

    # TODO: Builtins should not require value expressions
    elif isinstance(expected_arg_type, BaseTypeDefinition):
        return Expr.parse_value_expr(arg, context)

    # If the input value is a typestring, return the equivalent codegen type for IR generation
    elif isinstance(expected_arg_type, TypeTypeDefinition):
        return new_type_to_old_type(expected_arg_type.typedef)

    raise CompilerPanic(f"Unexpected type for builtin function argument: {expected_arg_type}")


def validate_inputs(wrapped_fn):
    """
    Validate input arguments on builtin functions.

    Applied as a wrapper on the `build_IR` method of
    classes in `vyper.functions.functions`.
    """

    @functools.wraps(wrapped_fn)
    def decorator_fn(self, node, context):
        arg_types = [a._metadata["type"] for a in node.args]
        kwargz = getattr(self, "_kwargs", {})
        assert len(node.args) == len(arg_types)
        subs = [process_arg(arg, arg_type, context) for arg, arg_type in zip(node.args, arg_types)]
        kwsubs = {}
        node_kw = {k.arg: k.value for k in node.keywords}
        node_kw_types = {k.arg: k.value._metadata["type"] for k in node.keywords}
        if kwargz:
            for k, expected_arg in self._kwargs.items():
                if k not in node_kw:
                    kwsubs[k] = expected_arg.default
                else:
                    # For literals, skip process_arg and set the AST node value
                    if expected_arg.require_literal:
                        kwsubs[k] = _process_optional_literal_value(expected_arg, node_kw[k])
                    else:
                        kwsubs[k] = process_arg(node_kw[k], node_kw_types[k], context)
        return wrapped_fn(self, node, subs, kwsubs, context)

    return decorator_fn
