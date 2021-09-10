from typing import Any, List, Union

from vyper import ast as vy_ast
from vyper.ast.signatures import sig_utils
from vyper.ast.signatures.function_signature import FunctionSignature
from vyper.old_codegen.arg_clamps import make_arg_clamper
from vyper.old_codegen.context import Context, VariableRecord
from vyper.old_codegen.expr import Expr
from vyper.old_codegen.function_definitions.utils import (
    get_default_names_to_set,
    get_nonreentrant_lock,
    get_sig_statements,
)
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import getpos, make_setter
from vyper.old_codegen.stmt import parse_body
from vyper.old_codegen.types.types import ByteArrayLike, get_size_of_type
from vyper.utils import MemoryPositions

# register function args with the local calling context.
# also allocate the ones that live in memory (i.e. kwargs)
def _register_function_args(context: Context, sig: FunctionSignature):

    if len(args) == 0:
        return

    # tuple with the abi_encoded args
    if sig.is_init_func():
        base_args_location = LLLnode("~codelen", location="code", typ=tbd_base_args_type)
    else:
        base_args_location = LLLnode(4, location="calldata", typ=tbd_base_args_type)

    base_args = lazy_abi_decode(tbd_base_args_type, base_args_location)

    assert base_args.value == "multi", "you've been bad"

    for (argname, arg_lll) in zip(tbd_argnames, base_args.args):  # the actual values
        # register the record in the local namespace
        context.vars[argname] = LLLnode(arg_lll, location=location)


def _generate_kwarg_handlers(context: Context, sig):
    # generate kwarg handlers.
    # since they might come in thru calldata or be default,
    # allocate them in memory and then fill it in based on calldata or default,
    # depending on the signature

    ret = []

    def handler_for(calldata_kwargs, default_kwargs):
        default_kwargs = [Expr(x, context).lll_node for x in default_kwargs]

        calldata_args = base_args + calldata_kwargs
        calldata_args_t = TupleType(list(arg.typ for arg in calldata_args))

        sig = func_name + canonicalize_type(calldata_args_t)
        method_id = util.method_id(sig)

        calldata_args_location = LLLnode(4, location="calldata", typ=calldata_args_t)

        calldata_args = lazy_abi_decode(calldata_args_t, base_args_location)

        assert calldata_args.value == "multi" # sanity check
        # extract just the kwargs from the ABI payload
        # TODO come up with a better name for these variables
        calldata_kwargs = calldata_args.args[:len(base_args)]

        # a sequence of statements to strictify kwargs into memory
        ret = ["seq"]

        all_kwargs_t = TupleType(list(arg.typ for arg in sig_kwargs))

        for x in calldata_kwargs:
            context.new_variable(argname, argtype, mutable=False)
            ret.append(make_setter(context.lookup_var(x.name), x, "memory"))
        for x in default_kwargs:
            context.new_variable(argname, argtype, mutable=False)
            ret.append(make_setter(context.lookup_var(x.name), Expr(x, context).lll_node, "memory"))

        ret.append(["goto", tbd_entry_point])

        ret = ["if", ["eq", tbd_mload_method_id, method_id], ret]
        return ret

    for i, kwarg in enumerate(keyword_args):
        calldata_kwargs = keyword_args[:i]
        default_kwargs = keyword_args[i:]

        sig = tbd_sig

        ret.append(handler_for(calldata_kwargs, default_kwargs))

    return ret


def generate_lll_for_external_function(
    code: vy_ast.FunctionDef, sig: FunctionSignature, context: Context, check_nonpayable: bool,
) -> LLLnode:
    func_type = code._metadata["type"]

    _register_function_args(context, sig)

    nonreentrant_pre, nonreentrant_post = get_nonreentrant_lock(func_type)

    kwarg_handlers = _generate_kwarg_handlers(context, sig)

    entrance = []

    # once args have been handled
    if len(kwarg_handlers) > 0:
        entrance.append(["label", f"{sig.base_method_id}_entry"])
    # TODO need a case for no kwargs?

    if check_nonpayable and sig.mutability != "payable":
        # if the contract contains payable functions, but this is not one of them
        # add an assertion that the value of the call is zero
        entrance.append(["assert", ["iszero", "callvalue"]])

    body = [parse_body(c, context) for c in code.body]

    exit = ([["label", func_type.exit_sequence_label]]
        + [nonreentrant_post]
        # TODO optimize case where return_type is None: use STOP
        + [["return", "pass", "pass"]] # ret_ofst and ret_len stack items passed by function body
        )

    ret = (["seq"]
            + arg_handlers
            + entrance
            + body
            + exit
            )
    # TODO special handling for default function
    if len(kwarg_handlers) == 0: # TODO is this check correct?
        ret = ["if", ["eq", tbd_mload_method_id, sig.method_id], ret]

    return LLLnode.from_list(ret, pos=getpos(code))
