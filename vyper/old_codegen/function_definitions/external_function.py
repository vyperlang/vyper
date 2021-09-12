from typing import Any, List

import vyper.utils as util
from vyper.ast.signatures.function_signature import (
    FunctionSignature,
    VariableRecord,
)
from vyper.old_codegen.abi import lazy_abi_decode
from vyper.old_codegen.context import Context
from vyper.old_codegen.expr import Expr
from vyper.old_codegen.function_definitions.utils import get_nonreentrant_lock
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import getpos, make_setter
from vyper.old_codegen.stmt import parse_body
from vyper.old_codegen.types.types import ListType, TupleType


# register function args with the local calling context.
# also allocate the ones that live in memory (i.e. kwargs)
# returns an LLLnode with copy operations for base args which
# need to be copied to memory (they don't play nicely with
# downstream code).
def _register_function_args(context: Context, sig: FunctionSignature) -> List[Any]:

    ret = ["seq"]

    if len(sig.args) == 0:
        return ret

    base_args_t = TupleType([arg.typ for arg in sig.base_args])

    # tuple with the abi_encoded args
    if sig.is_init_func:
        base_args_location = LLLnode("~codelen", location="code", typ=base_args_t)
    else:
        base_args_location = LLLnode(4, location="calldata", typ=base_args_t)

    base_args_lll = lazy_abi_decode(base_args_t, base_args_location)

    assert base_args_lll.value == "multi", "lazy_abi_decode did not return multi"
    base_args_lll = base_args_lll.args  # the (lazily) decoded values

    assert len(base_args_lll) == len(sig.base_args)
    for (arg, arg_lll) in zip(sig.base_args, base_args_lll):  # the actual values
        assert arg.typ == arg_lll.typ, (arg.typ, arg_lll.typ)

        if isinstance(arg.typ, ListType):
            assert arg_lll.value == "multi"
            # ListTypes might be accessed with add_variable_offset
            # which doesn't work for `multi`, so instead copy them
            # to memory.
            # TODO nested lists are still broken!
            dst_ofst = context.new_variable(arg.name, typ=arg.typ, is_mutable=False)
            dst = LLLnode(dst_ofst, typ=arg.typ, location="memory")
            x = make_setter(dst, arg_lll, "memory", pos=getpos(arg.ast_source))
            ret.append(x)
        else:
            # register the record in the local namespace, no copy needed
            context.vars[arg.name] = VariableRecord(
                name=arg.name, pos=arg_lll, typ=arg.typ, mutable=False, location=arg_lll.location
            )

    return ret


# TODO move me to function_signature.py?
def _base_entry_point(sig):
    return f"{sig.mk_identifier}_entry"


def _generate_kwarg_handlers(context: Context, sig: FunctionSignature, pos: Any) -> List[Any]:
    # generate kwarg handlers.
    # since they might come in thru calldata or be default,
    # allocate them in memory and then fill it in based on calldata or default,
    # depending on the signature

    def handler_for(calldata_kwargs, default_kwargs):
        calldata_args = sig.base_args + calldata_kwargs
        calldata_args_t = TupleType(list(arg.typ for arg in calldata_args))

        abi_sig = sig.abi_signature_for_args(calldata_args)
        method_id = util.abi_method_id(abi_sig)

        calldata_args_location = LLLnode(4, location="calldata", typ=calldata_args_t)

        calldata_args_lll = lazy_abi_decode(calldata_args_t, calldata_args_location)

        assert calldata_args_lll.value == "multi"  # sanity check
        # extract just the kwargs from the ABI payload
        calldata_kwargs_lll = calldata_args_lll.args[len(sig.base_args) :]  # noqa: E203

        # a sequence of statements to strictify kwargs into memory
        ret = ["seq"]

        # TODO optimize make_setter by using
        # TupleType(list(arg.typ for arg in calldata_kwargs + default_kwargs))

        lhs_location = "memory"
        assert len(calldata_kwargs_lll) == len(calldata_kwargs), calldata_kwargs
        for arg_meta, arg_lll in zip(calldata_kwargs, calldata_kwargs_lll):
            assert arg_meta.typ == arg_lll.typ
            dst = context.new_variable(arg_meta.name, arg_meta.typ, is_mutable=False)
            lhs = LLLnode(dst, location="memory", typ=arg_meta.typ)
            rhs = arg_lll
            ret.append(make_setter(lhs, rhs, lhs_location, pos))
        for x in default_kwargs:
            dst = context.new_variable(x.name, x.typ, is_mutable=False)
            lhs = LLLnode(dst, location="memory", typ=x.typ)
            kw_ast_val = sig.default_values[x.name]  # e.g. `3` in x: int = 3
            rhs = Expr(kw_ast_val, context).lll_node
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
def generate_lll_for_external_function(code, sig, context, check_nonpayable):
    # TODO type hints:
    # def generate_lll_for_external_function(
    #    code: vy_ast.FunctionDef, sig: FunctionSignature, context: Context, check_nonpayable: bool,
    # ) -> LLLnode:
    """Return the LLL for an external function. Includes code to inspect the method_id,
       enter the function (nonpayable and reentrancy checks), handle kwargs and exit
       the function (clean up reentrancy storage variables)
    """
    func_type = code._metadata["type"]
    pos = getpos(code)

    base_arg_handlers = _register_function_args(context, sig)

    nonreentrant_pre, nonreentrant_post = get_nonreentrant_lock(func_type)

    kwarg_handlers = _generate_kwarg_handlers(context, sig, pos)

    entrance = [base_arg_handlers]

    # once args have been handled
    if len(kwarg_handlers) > 1:
        entrance += [["label", _base_entry_point(sig)]]
    else:
        # otherwise, the label is redundant since there is only
        # one control flow path into the external method
        pass

    if check_nonpayable and sig.mutability != "payable":
        # if the contract contains payable functions, but this is not one of them
        # add an assertion that the value of the call is zero
        entrance += [["assert", ["iszero", "callvalue"]]]

    entrance += nonreentrant_pre

    body = [parse_body(c, context) for c in code.body]

    exit = [["label", sig.exit_sequence_label]] + nonreentrant_post
    if context.return_type is None:
        exit += [["stop"]]
    else:
        # ret_ofst and ret_len stack items passed by function body; consume using 'pass'
        exit += [["return", "pass", "pass"]]

    ret = ["seq"] + kwarg_handlers + entrance + body + exit

    # TODO special handling for default function
    if len(kwarg_handlers) == 0:
        _sigs = sig.all_kwarg_sigs
        assert len(_sigs) == 1
        _method_id = util.abi_method_id(_sigs[0])
        ret = ["if", ["eq", "_calldata_method_id", _method_id], ret]

    return LLLnode.from_list(ret, pos=getpos(code))
