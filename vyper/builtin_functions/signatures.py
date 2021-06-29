import functools

from vyper import ast as vy_ast
from vyper.exceptions import InvalidLiteral, StructureException, TypeMismatch
from vyper.old_codegen.expr import Expr
from vyper.old_codegen.types import (
    BaseType,
    ByteArrayType,
    StringType,
    is_base_type,
)
from vyper.utils import SizeLimits


class Optional(object):
    def __init__(self, typ, default):
        self.typ = typ
        self.default = default


def process_arg(index, arg, expected_arg_typelist, function_name, context):

    # temporary hack to support abstract types
    if hasattr(expected_arg_typelist, "_id_list"):
        expected_arg_typelist = expected_arg_typelist._id_list

    if isinstance(expected_arg_typelist, Optional):
        expected_arg_typelist = expected_arg_typelist.typ
    if not isinstance(expected_arg_typelist, tuple):
        expected_arg_typelist = (expected_arg_typelist,)

    vsub = None
    for expected_arg in expected_arg_typelist:

        # temporary hack, once we refactor this package none of this will exist
        if hasattr(expected_arg, "_id"):
            expected_arg = expected_arg._id

        if expected_arg == "num_literal":
            if isinstance(arg, (vy_ast.Int, vy_ast.Decimal)):
                return arg.n
        elif expected_arg == "str_literal":
            if isinstance(arg, vy_ast.Str):
                bytez = b""
                for c in arg.s:
                    if ord(c) >= 256:
                        raise InvalidLiteral(
                            f"Cannot insert special character {c} into byte array", arg,
                        )
                    bytez += bytes([ord(c)])
                return bytez
        elif expected_arg == "bytes_literal":
            if isinstance(arg, vy_ast.Bytes):
                return arg.s
        elif expected_arg == "name_literal":
            if isinstance(arg, vy_ast.Name):
                return arg.id
            elif isinstance(arg, vy_ast.Subscript) and arg.value.id == "Bytes":
                return f"Bytes[{arg.slice.value.n}]"
        elif expected_arg == "*":
            return arg
        elif expected_arg == "Bytes":
            sub = Expr(arg, context).lll_node
            if isinstance(sub.typ, ByteArrayType):
                return sub
        elif expected_arg == "String":
            sub = Expr(arg, context).lll_node
            if isinstance(sub.typ, StringType):
                return sub
        else:
            # Does not work for unit-endowed types inside compound types, e.g. timestamp[2]
            parsed_expected_type = context.parse_type(
                vy_ast.parse_to_ast(expected_arg)[0].value, "memory",
            )
            if isinstance(parsed_expected_type, BaseType):
                vsub = vsub or Expr.parse_value_expr(arg, context)

                is_valid_integer = (
                    (expected_arg in ("int128", "uint256") and isinstance(vsub.typ, BaseType))
                    and (vsub.typ.typ in ("int128", "uint256") and vsub.typ.is_literal)
                    and (SizeLimits.in_bounds(expected_arg, vsub.value))
                )

                if is_base_type(vsub.typ, expected_arg):
                    return vsub
                elif is_valid_integer:
                    return vsub
            else:
                vsub = vsub or Expr(arg, context).lll_node
                if vsub.typ == parsed_expected_type:
                    return Expr(arg, context).lll_node
    if len(expected_arg_typelist) == 1:
        raise TypeMismatch(f"Expecting {expected_arg} for argument {index} of {function_name}", arg)
    else:
        raise TypeMismatch(
            f"Expecting one of {expected_arg_typelist} for argument {index} of {function_name}", arg
        )


def signature(*argz, **kwargz):
    def decorator(f):
        @functools.wraps(f)
        def g(element, context):
            function_name = element.func.id
            if len(element.args) > len(argz):
                raise StructureException(
                    f"Expected {len(argz)} arguments for {function_name}, "
                    f"got {len(element.args)}",
                    element,
                )
            subs = []
            for i, expected_arg in enumerate(argz):
                if len(element.args) > i:
                    subs.append(
                        process_arg(i + 1, element.args[i], expected_arg, function_name, context,)
                    )
                elif isinstance(expected_arg, Optional):
                    subs.append(expected_arg.default)
                else:
                    raise StructureException(
                        f"Not enough arguments for function: {element.func.id}", element
                    )
            kwsubs = {}
            element_kw = {k.arg: k.value for k in element.keywords}
            for k, expected_arg in kwargz.items():
                if k not in element_kw:
                    if isinstance(expected_arg, Optional):
                        kwsubs[k] = expected_arg.default
                    else:
                        raise StructureException(
                            f"Function {function_name} requires argument {k}", element
                        )
                else:
                    kwsubs[k] = process_arg(k, element_kw[k], expected_arg, function_name, context)
            for k, _arg in element_kw.items():
                if k not in kwargz:
                    raise StructureException(f"Unexpected argument: {k}", element)
            return f(element, subs, kwsubs, context)

        return g

    return decorator


def validate_inputs(wrapped_fn):
    """
    Validate input arguments on builtin functions.

    Applied as a wrapper on the `build_LLL` method of
    classes in `vyper.functions.functions`.
    """

    @functools.wraps(wrapped_fn)
    def decorator_fn(self, node, context):
        argz = [i[1] for i in self._inputs]
        kwargz = getattr(self, "_kwargs", {})
        function_name = node.func.id
        if len(node.args) > len(argz):
            raise StructureException(
                f"Expected {len(argz)} arguments for {function_name}, got {len(node.args)}", node
            )
        subs = []
        for i, expected_arg in enumerate(argz):
            if len(node.args) > i:
                subs.append(process_arg(i + 1, node.args[i], expected_arg, function_name, context,))
            elif isinstance(expected_arg, Optional):
                subs.append(expected_arg.default)
            else:
                raise StructureException(f"Not enough arguments for function: {node.func.id}", node)
        kwsubs = {}
        node_kw = {k.arg: k.value for k in node.keywords}
        for k, expected_arg in kwargz.items():
            if k not in node_kw:
                if not isinstance(expected_arg, Optional):
                    raise StructureException(
                        f"Function {function_name} requires argument {k}", node
                    )
                kwsubs[k] = expected_arg.default
            else:
                kwsubs[k] = process_arg(k, node_kw[k], expected_arg, function_name, context)
        for k, _arg in node_kw.items():
            if k not in kwargz:
                raise StructureException(f"Unexpected argument: {k}", node)
        return wrapped_fn(self, node, subs, kwsubs, context)

    return decorator_fn
