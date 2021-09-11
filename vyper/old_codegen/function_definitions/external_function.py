from typing import Any

import vyper.utils as util
from vyper import ast as vy_ast
from vyper.ast.signatures.function_signature import FunctionSignature
from vyper.old_codegen.abi import lazy_abi_decode
from vyper.old_codegen.context import Context
from vyper.old_codegen.expr import Expr
from vyper.old_codegen.function_definitions.utils import get_nonreentrant_lock
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import getpos, make_setter
from vyper.old_codegen.stmt import parse_body
from vyper.old_codegen.types.types import TupleType, canonicalize_type


# register function args with the local calling context.
# also allocate the ones that live in memory (i.e. kwargs)
def _register_function_args(context: Context, sig: FunctionSignature):

    if len(sig.args) == 0:
        return

    base_args_t = TupleType([arg.typ for arg in sig.base_args])

    # tuple with the abi_encoded args
    if sig.is_init_func():
        base_args_location = LLLnode("~codelen", location="code", typ=base_args_t)
    else:
        base_args_location = LLLnode(4, location="calldata", typ=base_args_t)

    base_args = lazy_abi_decode(base_args_t, base_args_location)

    assert base_args.value == "multi", "lazy_abi_decode did not return multi"
    base_args = base_args.args  # the (lazily) decoded values

    assert len(base_args) == len(sig.base_args)
    for (arg, arg_lll) in zip(sig.base_args, base_args.args):  # the actual values
        assert arg.typ == arg_lll.typ
        # register the record in the local namespace
        context.vars[arg.name] = LLLnode(arg_lll, location=base_args_location)


def _base_entry_point(sig):
    return f"{sig.base_method_id}_entry"


def _generate_kwarg_handlers(context: Context, sig: FunctionSignature, pos: Any):
    # generate kwarg handlers.
    # since they might come in thru calldata or be default,
    # allocate them in memory and then fill it in based on calldata or default,
    # depending on the signature

    def handler_for(calldata_kwargs, default_kwargs):
        default_kwargs = [Expr(x, context).lll_node for x in default_kwargs]

        calldata_args = sig.base_args + calldata_kwargs
        calldata_args_t = TupleType(list(arg.typ for arg in calldata_args))

        abi_sig = sig.name + canonicalize_type(calldata_args_t)
        method_id = util.method_id(abi_sig)

        calldata_args_location = LLLnode(4, location="calldata", typ=calldata_args_t)

        calldata_args = lazy_abi_decode(calldata_args_t, calldata_args_location)

        assert calldata_args.value == "multi"  # sanity check
        # extract just the kwargs from the ABI payload
        # TODO come up with a better name for these variables
        calldata_kwargs = calldata_args.args[: len(sig.base_args)]

        # a sequence of statements to strictify kwargs into memory
        ret = ["seq"]

        # TODO optimize make_setter by using
        # TupleType(list(arg.typ for arg in calldata_kwargs + default_kwargs))

        lhs_location = "memory"
        for x in calldata_kwargs:
            context.new_variable(x.name, x.typ, mutable=False)
            lhs = context.lookup_var(x.name)
            rhs = x
            ret.append(make_setter(lhs, rhs, lhs_location, pos))
        for x in default_kwargs:
            context.new_variable(x.name, x.typ, mutable=False)
            lhs = context.lookup_var(x.name)
            rhs = Expr(x, context).lll_node
            ret.append(make_setter(lhs, rhs, lhs_location, pos))

        ret.append(["goto", _base_entry_point(sig)])

        ret = ["if", ["eq", "_calldata_method_id", method_id], ret]
        return ret

    ret = ["seq"]

    keyword_args = sig.default_args

    for i, _ in enumerate(keyword_args):
        calldata_kwargs = keyword_args[:i]
        default_kwargs = keyword_args[i:]

        ret.append(handler_for(calldata_kwargs, default_kwargs))

    return ret


# TODO it would be nice if this returned a data structure which were
# amenable to generating a jump table instead of the linear search for
# method_id we have now.
def generate_lll_for_external_function(
    code: vy_ast.FunctionDef, sig: FunctionSignature, context: Context, check_nonpayable: bool,
) -> LLLnode:
    """Return the LLL for an external function. Includes code to inspect the method_id,
       enter the function (nonpayable and reentrancy checks), handle kwargs and exit
       the function (clean up reentrancy storage variables)
    """
    func_type = code._metadata["type"]
    pos = getpos(code)

    _register_function_args(context, sig)

    nonreentrant_pre, nonreentrant_post = get_nonreentrant_lock(func_type)

    kwarg_handlers = _generate_kwarg_handlers(context, sig, pos)

    entrance = []

    # once args have been handled
    if len(kwarg_handlers) > 0:
        entrance.append(["label", _base_entry_point(sig)])

    if check_nonpayable and sig.mutability != "payable":
        # if the contract contains payable functions, but this is not one of them
        # add an assertion that the value of the call is zero
        entrance.append(["assert", ["iszero", "callvalue"]])

    body = [parse_body(c, context) for c in code.body]

    exit = [["label", func_type.exit_sequence_label]] + [nonreentrant_post]
    if context.return_type is None:
        exit += [["stop"]]
    else:
        # ret_ofst and ret_len stack items passed by function body; consume using 'pass'
        exit += [["return", "pass", "pass"]]

    ret = ["seq"] + kwarg_handlers + entrance + body + exit

    # TODO special handling for default function
    if len(kwarg_handlers) == 0:
        ret = ["if", ["eq", "_calldata_method_id", sig.method_id], ret]

    return LLLnode.from_list(ret, pos=getpos(code))
