from functools import wraps

from vyper.codegen.expr import Expr
from vyper.codegen.ir_node import IRnode
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import TYPE_T, VyperType


def process_arg(arg, expected_arg_type, context):
    # If the input value is a typestring, return the equivalent codegen type for IR generation
    if isinstance(expected_arg_type, TYPE_T):
        return expected_arg_type.typedef

    # if it is a word type, return a stack item.
    # TODO: remove this case, builtins should not require value expressions
    if expected_arg_type._is_prim_word:
        return Expr.parse_value_expr(arg, context)

    if isinstance(expected_arg_type, VyperType):
        return Expr(arg, context).ir_node

    raise CompilerPanic(f"Unexpected type: {expected_arg_type}")  # pragma: notest


def process_kwarg(kwarg_node, kwarg_settings, expected_kwarg_type, context):
    if kwarg_settings.require_literal:
        return kwarg_node.value

    return process_arg(kwarg_node, expected_kwarg_type, context)


def process_inputs(wrapped_fn):
    """
    Generate IR for input arguments on builtin functions.

    Applied as a wrapper on the `build_IR` method of
    classes in `vyper.functions.functions`.
    """

    @wraps(wrapped_fn)
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
