import functools

from vyper.ast import nodes as vy_ast
from vyper.codegen.expr import Expr
from vyper.codegen.types.convert import new_type_to_old_type
from vyper.exceptions import CompilerPanic, TypeMismatch
from vyper.semantics.types import (
    ArrayDefinition,
    BytesArrayDefinition,
    DynamicArrayDefinition,
    StringDefinition,
)
from vyper.semantics.types.bases import BaseTypeDefinition


class TypeTypeDefinition:
    def __init__(self, typedef):
        self.typedef = typedef

    def __repr__(self):
        return f"type({self.typedef})"


def process_arg(arg, expected_arg_type, context):
    if isinstance(
        expected_arg_type,
        (BytesArrayDefinition, StringDefinition, ArrayDefinition, DynamicArrayDefinition),
    ):
        return Expr(arg, context).ir_node

    # TODO: Builtins should not require value expressions
    elif isinstance(expected_arg_type, BaseTypeDefinition):
        return Expr.parse_value_expr(arg, context)

    # If the input value is a typestring, return the equivalent codegen type for IR generation
    elif isinstance(expected_arg_type, TypeTypeDefinition):
        return new_type_to_old_type(expected_arg_type.typedef)

    raise CompilerPanic(f"Unexpected type: {expected_arg_type}")  # pragma: notest


def process_kwarg(kwarg_node, kwarg_settings, context):
    if kwarg_settings.require_literal:
        if not isinstance(kwarg_node, vy_ast.Constant):
            raise TypeMismatch("Value for kwarg must be a literal", kwarg_node)

        return kwarg_node.value

    return process_arg(kwarg_node, kwarg_settings.typ, context)


def validate_inputs(wrapped_fn):
    """
    Validate input arguments on builtin functions.

    Applied as a wrapper on the `build_IR` method of
    classes in `vyper.functions.functions`.
    """

    @functools.wraps(wrapped_fn)
    def decorator_fn(self, node, context):
        subs = []
        for arg in node.args:
            subs.append(process_arg(arg, arg._metadata["type"], context))

        kwsubs = {}

        # note: must compile in source code order, left-to-right
        for k in node.keywords:
            kwarg_settings = self._kwargs[k.arg]
            kwsubs[k.arg] = process_kwarg(k.value, kwarg_settings, context)

        # add kwargs which were not specified in the source
        for k, expected_arg in self._kwargs.items():
            if k not in kwsubs:
                kwsubs[k] = expected_arg.default

        return wrapped_fn(self, node, subs, kwsubs, context)

    return decorator_fn
