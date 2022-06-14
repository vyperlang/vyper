import functools
from typing import Dict

from vyper.ast import nodes as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.codegen.expr import Expr
from vyper.codegen.ir_node import IRnode
from vyper.codegen.types.convert import new_type_to_old_type
from vyper.exceptions import CompilerPanic, TypeMismatch
from vyper.semantics.types import (
    ArrayDefinition,
    BytesArrayDefinition,
    DynamicArrayDefinition,
    StringDefinition,
)
from vyper.semantics.types.bases import BaseTypeDefinition
from vyper.semantics.types.utils import KwargSettings, TypeTypeDefinition
from vyper.semantics.validation.utils import get_exact_type_from_node, validate_expected_type


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


def process_kwarg(kwarg_node, kwarg_settings, expected_kwarg_type, context):
    if kwarg_settings.require_literal:
        if not isinstance(kwarg_node, vy_ast.Constant):
            raise TypeMismatch("Value for kwarg must be a literal", kwarg_node)

        return kwarg_node.value

    return process_arg(kwarg_node, expected_kwarg_type, context)


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
            arg_ir = process_arg(arg, arg._metadata["type"], context)
            # TODO annotate arg_ir with argname from self._inputs?
            subs.append(arg_ir)

        kwsubs = {}

        # note: must compile in source code order, left-to-right
        expected_kwarg_types = self.infer_kwarg_types(node)
        for k in node.keywords:
            kwarg_settings = self._kwargs[k.arg]
            expected_kwarg_type = expected_kwarg_types[k.arg]
            kwsubs[k.arg] = process_kwarg(k.value, kwarg_settings, expected_kwarg_type, context)

        # add kwargs which were not specified in the source
        for k, expected_arg in self._kwargs.items():
            if k not in kwsubs:
                kwsubs[k] = expected_arg.default

        for k, v in kwsubs.items():
            if isinstance(v, IRnode):
                v.annotation = k

        return wrapped_fn(self, node, subs, kwsubs, context)

    return decorator_fn


# TODO: rename me to BuiltinFunction
class _SimpleBuiltinFunction:

    _has_varargs = False
    _kwargs: Dict[str, KwargSettings] = {}

    def _validate_arg_types(self, node):
        num_args = len(self._inputs)  # the number of args the signature indicates

        expect_num_args = num_args
        if self._has_varargs:
            # note special meaning for -1 in validate_call_args API
            expect_num_args = (num_args, -1)

        validate_call_args(node, expect_num_args, getattr(self, "_kwargs", []))

        for arg, (_, expected) in zip(node.args, self._inputs):
            validate_expected_type(arg, expected)

        # typecheck varargs. we don't have type info from the signature,
        # so ensure that the types of the args can be inferred exactly.
        varargs = node.args[num_args:]
        if len(varargs) > 0:
            assert self._has_varargs  # double check validate_call_args
        for arg in varargs:
            # call get_exact_type_from_node for its side effects -
            # ensures the type can be inferred exactly.
            get_exact_type_from_node(arg)

    def fetch_call_return(self, node):
        self._validate_arg_types(node)

        if self._return_type:
            return self._return_type

    def infer_arg_types(self, node):
        self._validate_arg_types(node)
        ret = [expected for (_, expected) in self._inputs]

        # handle varargs.
        n_known_args = len(self._inputs)
        varargs = node.args[n_known_args:]
        if len(varargs) > 0:
            assert self._has_varargs
        ret.extend(get_exact_type_from_node(arg) for arg in varargs)
        return ret

    def infer_kwarg_types(self, node):
        return {i.arg: self._kwargs[i.arg].typ for i in node.keywords}

    def __repr__(self):
        return f"(builtin) {self._id}"
