import functools

from vyper import ast as vy_ast
from vyper.codegen.expr import Expr
from vyper.exceptions import InvalidLiteral, StructureException
from vyper.semantics.types.abstract import UnsignedIntegerAbstractType
from vyper.semantics.types.bases import BaseTypeDefinition
from vyper.semantics.types.value.array_value import BytesArrayDefinition, StringDefinition


class Optional(object):
    def __init__(self, typ, default):
        self.typ = typ
        self.default = default


class TypeTypeDefinition:
    def __init__(self, typestr):
        self.typestr = typestr

    def __repr__(self):
        return f"type({self.typestr})"


def process_arg(index, arg, expected_arg, function_name, context):
    # Workaround for non-empty topics argument to raw_log
    if isinstance(arg, vy_ast.List):
        ret = []
        for a in arg.elements:
            r = Expr.parse_value_expr(a, context)
            ret.append(r)
        return ret

    if isinstance(expected_arg, (BytesArrayDefinition, StringDefinition)):
        return Expr(arg, context).ir_node

    elif isinstance(expected_arg, BaseTypeDefinition):
        return Expr.parse_value_expr(arg, context)

    elif isinstance(expected_arg, TypeTypeDefinition):
        return expected_arg.typestr

    elif isinstance(expected_arg, UnsignedIntegerAbstractType):
        if isinstance(arg, (vy_ast.Int, vy_ast.Decimal)):
            return arg.n

    else:
        # Workaround for empty topics argument to raw_log
        if expected_arg is None:
            return arg

        elif expected_arg == "str_literal":
            bytez = b""
            for c in arg.s:
                if ord(c) >= 256:
                    raise InvalidLiteral(
                        f"Cannot insert special character {c} into byte array",
                        arg,
                    )
                bytez += bytes([ord(c)])
            return bytez


def validate_inputs(wrapped_fn):
    """
    Validate input arguments on builtin functions.

    Applied as a wrapper on the `build_IR` method of
    classes in `vyper.functions.functions`.
    """

    @functools.wraps(wrapped_fn)
    def decorator_fn(self, node, context):
        argz = self.infer_arg_types(node)
        kwargz = getattr(self, "_kwargs", {})
        function_name = node.func.id
        if len(node.args) > len(argz):
            raise StructureException(
                f"Expected {len(argz)} arguments for {function_name}, got {len(node.args)}", node
            )
        subs = []
        for i, expected_arg in enumerate(argz):
            if len(node.args) > i:
                subs.append(
                    process_arg(
                        i + 1,
                        node.args[i],
                        expected_arg,
                        function_name,
                        context,
                    )
                )
            elif isinstance(expected_arg, Optional):
                subs.append(expected_arg.default)
            else:
                raise StructureException(f"Not enough arguments for function: {node.func.id}", node)
        kwsubs = {}
        node_kw = {k.arg: k.value for k in node.keywords}
        node_kw_types = self.infer_kwarg_types(node)
        if kwargz:
            for k, expected_arg in self._kwargs.items():
                if k not in node_kw:
                    kwsubs[k] = expected_arg.default
                else:
                    kwsubs[k] = process_arg(k, node_kw[k], node_kw_types[k], function_name, context)
            for k, _arg in node_kw.items():
                if k not in kwargz:
                    raise StructureException(f"Unexpected argument: {k}", node)
        return wrapped_fn(self, node, subs, kwsubs, context)

    return decorator_fn
