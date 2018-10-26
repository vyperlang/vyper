import ast

from vyper.parser.parser_utils import (
    get_original_if_0_prefixed,
)
from vyper.exceptions import (
    TypeMismatchException,
    StructureException,
    InvalidLiteralException,
)
from vyper.types import (
    BaseType,
    ByteArrayType
)
from vyper.types import (
    parse_type,
    is_base_type
)
from vyper.parser.expr import (
    Expr,
)
from vyper.utils import (
    SizeLimits
)


class Optional(object):
    def __init__(self, typ, default):
        self.typ = typ
        self.default = default


def process_arg(index, arg, expected_arg_typelist, function_name, context):
    if isinstance(expected_arg_typelist, Optional):
        expected_arg_typelist = expected_arg_typelist.typ
    if not isinstance(expected_arg_typelist, tuple):
        expected_arg_typelist = (expected_arg_typelist, )
    vsub = None
    for expected_arg in expected_arg_typelist:
        if expected_arg == 'num_literal':
            if isinstance(arg, ast.Num) and get_original_if_0_prefixed(arg, context) is None:
                return arg.n
        elif expected_arg == 'str_literal':
            if isinstance(arg, ast.Str) and get_original_if_0_prefixed(arg, context) is None:
                bytez = b''
                for c in arg.s:
                    if ord(c) >= 256:
                        raise InvalidLiteralException("Cannot insert special character %r into byte array" % c, arg)
                    bytez += bytes([ord(c)])
                return bytez
        elif expected_arg == 'name_literal':
            if isinstance(arg, ast.Name):
                return arg.id
            elif isinstance(arg, ast.Subscript) and arg.value.id == 'bytes':
                return 'bytes[%s]' % arg.slice.value.n
        elif expected_arg == '*':
            return arg
        elif expected_arg == 'bytes':
            sub = Expr(arg, context).lll_node
            if isinstance(sub.typ, ByteArrayType):
                return sub
        else:
            # Does not work for unit-endowed types inside compound types, e.g. timestamp[2]
            parsed_expected_type = parse_type(ast.parse(expected_arg).body[0].value, 'memory')
            if isinstance(parsed_expected_type, BaseType):
                vsub = vsub or Expr.parse_value_expr(arg, context)
                if is_base_type(vsub.typ, expected_arg):
                    return vsub
                elif expected_arg in ('int128', 'uint256') and isinstance(vsub.typ, BaseType) and \
                     vsub.typ.is_literal and SizeLimits.in_bounds(expected_arg, vsub.value):
                    return vsub
            else:
                vsub = vsub or Expr(arg, context).lll_node
                if vsub.typ == parsed_expected_type:
                    return Expr(arg, context).lll_node
    if len(expected_arg_typelist) == 1:
        raise TypeMismatchException("Expecting %s for argument %r of %s" %
                                    (expected_arg, index, function_name), arg)
    else:
        raise TypeMismatchException("Expecting one of %r for argument %r of %s" %
                                    (expected_arg_typelist, index, function_name), arg)
        return arg.id


def signature(*argz, **kwargz):
    def decorator(f):
        def g(element, context):
            function_name = element.func.id
            if len(element.args) > len(argz):
                raise StructureException("Expected %d arguments for %s, got %d" %
                                         (len(argz), function_name, len(element.args)),
                                         element)
            subs = []
            for i, expected_arg in enumerate(argz):
                if len(element.args) > i:
                    subs.append(process_arg(i + 1, element.args[i], expected_arg, function_name, context))
                elif isinstance(expected_arg, Optional):
                    subs.append(expected_arg.default)
                else:
                    raise StructureException(
                        "Not enough arguments for function: {}".format(element.func.id),
                        element
                    )
            kwsubs = {}
            element_kw = {k.arg: k.value for k in element.keywords}
            for k, expected_arg in kwargz.items():
                if k not in element_kw:
                    if isinstance(expected_arg, Optional):
                        kwsubs[k] = expected_arg.default
                    else:
                        raise StructureException("Function %s requires argument %s" %
                                                 (function_name, k), element)
                else:
                    kwsubs[k] = process_arg(k, element_kw[k], expected_arg, function_name, context)
            for k, arg in element_kw.items():
                if k not in kwargz:
                    raise StructureException("Unexpected argument: %s"
                                             % k, element)
            return f(element, subs, kwsubs, context)
        return g
    return decorator
