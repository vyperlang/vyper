from typing import Any, List

import vyper.utils as util
from vyper.ast.signatures.function_signature import (
    FunctionSignature,
    VariableRecord,
)
from vyper.exceptions import CompilerPanic
from vyper.old_codegen.context import Context
from vyper.old_codegen.expr import Expr
from vyper.old_codegen.function_definitions.utils import get_nonreentrant_lock
from vyper.old_codegen.lll_node import Encoding, LLLnode
from vyper.old_codegen.parser_utils import get_element_ptr, getpos, make_setter
from vyper.old_codegen.stmt import parse_body
from vyper.old_codegen.types.types import (
    BaseType,
    ByteArrayLike,
    ListType,
    TupleLike,
    TupleType,
)


def _should_decode(typ):
    # either a basetype which needs to be clamped
    # or a complex type which contains something that
    # needs to be clamped.
    if isinstance(typ, BaseType):
        return typ.typ not in ("int256", "uint256", "bytes32")
    if isinstance(typ, ByteArrayLike):
        return True
    if isinstance(typ, ListType):
        return _should_decode(typ.subtype)
    if isinstance(typ, TupleLike):
        return any(_should_decode(t) for t in typ.tuple_members())
    raise CompilerPanic(f"_should_decode({typ})")


# register function args with the local calling context.
# also allocate the ones that live in memory (i.e. kwargs)
def _register_function_args(context: Context, sig: FunctionSignature) -> List[LLLnode]:
    pos = None

    ret = []

    # the type of the calldata
    base_args_t = TupleType([arg.typ for arg in sig.base_args])

    # tuple with the abi_encoded args
    if sig.is_init_func:
        base_args_ofst = LLLnode(
            "~codelen", location="code", typ=base_args_t, encoding=Encoding.ABI
        )
    else:
        base_args_ofst = LLLnode(4, location="calldata", typ=base_args_t, encoding=Encoding.ABI)

    for i, arg in enumerate(sig.base_args):

        arg_lll = get_element_ptr(base_args_ofst, i, pos=pos)

        if _should_decode(arg.typ):
            # allocate a memory slot for it and copy
            p = context.new_variable(arg.name, arg.typ, is_mutable=False)
            dst = LLLnode(p, typ=arg.typ, location="memory")
            ret.append(make_setter(dst, arg_lll, pos=pos))
        else:
            # leave it in place
            context.vars[arg.name] = VariableRecord(
                name=arg.name,
                pos=arg_lll,
                typ=arg.typ,
                mutable=False,
                location=arg_lll.location,
                encoding=Encoding.ABI,
            )

    return ret


def _annotated_method_id(abi_sig):
    method_id = util.abi_method_id(abi_sig)
    annotation = f"{hex(method_id)}: {abi_sig}"
    return LLLnode(method_id, annotation=annotation)


def _generate_kwarg_handlers(context: Context, sig: FunctionSignature, pos: Any) -> List[Any]:
    # generate kwarg handlers.
    # since they might come in thru calldata or be default,
    # allocate them in memory and then fill it in based on calldata or default,
    # depending on the signature
    # a kwarg handler looks like
    # (if (eq _method_id <method_id>)
    #    copy calldata args to memory
    #    write default args to memory
    #    goto external_function_common_lll

    def handler_for(calldata_kwargs, default_kwargs):
        calldata_args = sig.base_args + calldata_kwargs
        # create a fake type so that get_element_ptr works
        calldata_args_t = TupleType(list(arg.typ for arg in calldata_args))

        abi_sig = sig.abi_signature_for_kwargs(calldata_kwargs)
        method_id = _annotated_method_id(abi_sig)

        calldata_kwargs_ofst = LLLnode(
            4, location="calldata", typ=calldata_args_t, encoding=Encoding.ABI
        )

        # a sequence of statements to strictify kwargs into memory
        ret = ["seq"]

        # TODO optimize make_setter by using
        # TupleType(list(arg.typ for arg in calldata_kwargs + default_kwargs))
        # (must ensure memory area is contiguous)

        n_base_args = len(sig.base_args)

        for i, arg_meta in enumerate(calldata_kwargs):
            k = n_base_args + i

            dst = context.lookup_var(arg_meta.name).pos

            lhs = LLLnode(dst, location="memory", typ=arg_meta.typ)
            rhs = get_element_ptr(calldata_kwargs_ofst, k, pos=None, array_bounds_check=False)
            ret.append(make_setter(lhs, rhs, pos))

        for x in default_kwargs:
            dst = context.lookup_var(x.name).pos
            lhs = LLLnode(dst, location="memory", typ=x.typ)
            kw_ast_val = sig.default_values[x.name]  # e.g. `3` in x: int = 3
            rhs = Expr(kw_ast_val, context).lll_node
            ret.append(make_setter(lhs, rhs, pos))

        ret.append(["goto", sig.external_function_base_entry_label])

        ret = ["if", ["eq", "_calldata_method_id", method_id], ret]
        return ret

    ret = ["seq"]

    keyword_args = sig.default_args

    # allocate variable slots in memory
    for arg in keyword_args:
        context.new_variable(arg.name, arg.typ, is_mutable=False)

    for i, _ in enumerate(keyword_args):
        calldata_kwargs = keyword_args[:i]
        default_kwargs = keyword_args[i:]

        ret.append(handler_for(calldata_kwargs, default_kwargs))

    ret.append(handler_for(keyword_args, []))

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

    nonreentrant_pre, nonreentrant_post = get_nonreentrant_lock(func_type)

    # generate handlers for base args and register the variable records
    handle_base_args = _register_function_args(context, sig)

    # generate handlers for kwargs and register the variable records
    kwarg_handlers = _generate_kwarg_handlers(context, sig, pos)

    # once optional args have been handled,
    # generate the main body of the function
    entrance = [["label", sig.external_function_base_entry_label]]

    entrance += handle_base_args

    if check_nonpayable and sig.mutability != "payable":
        # if the contract contains payable functions, but this is not one of them
        # add an assertion that the value of the call is zero
        entrance += [["assert", ["iszero", "callvalue"]]]

    entrance += nonreentrant_pre

    body = [parse_body(c, context) for c in code.body]

    exit = [["label", sig.exit_sequence_label]] + nonreentrant_post
    if sig.is_init_func:
        pass  # init func has special exit sequence generated by parser.py
    elif context.return_type is None:
        exit += [["stop"]]
    else:
        # ret_ofst and ret_len stack items passed by function body; consume using 'pass'
        exit += [["return", "pass", "pass"]]

    # the lll which comprises the main body of the function,
    # besides any kwarg handling
    func_common_lll = ["seq"] + entrance + body + exit

    if sig.is_default_func or sig.is_init_func:
        # default and init funcs have special entries generated by parser.py
        ret = func_common_lll
    else:
        ret = kwarg_handlers
        # sneak the base code into the kwarg handler
        # TODO rethink this / make it clearer
        ret[-1][-1].append(func_common_lll)

    return LLLnode.from_list(ret, pos=getpos(code))
