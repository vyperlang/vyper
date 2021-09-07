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

    if len(args) > 0:
        # tuple with the abi_encoded args
        base_args_location = LLLnode(4, location="calldata", typ=tbd_base_args_type)
        base_args = lazy_abi_decode(tbd_base_args_type, base_args_location)

        assert base_args.value == "multi"
        for (argname, arg_lll) in zip(tbd_argnames, base_args.args):  # the actual values
            # register the record in the local namespace
            context.vars[argname] = LLLnode(arg_lll, location="calldata")


def _generate_all_signatures(context: Context, function_def: vy_ast.FunctionDef):
    for sig, kwarg_value in zip(all_sigs, kwarg_values):
        yield pass


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
        calldata_args = calldata.args[len(base_args):]

        # a sequence of statements to strictify kwargs into memory
        ret = ["seq"]

        all_kwargs_t = TupleType(list(arg.typ for arg in sig_kwargs))

        all_kwargs_src = LLLnode.from_list(["multi"] + calldata_args + default_args, typ=all_kwargs_t)

        for x in calldata_args:
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

    # once kwargs have been handled
    if len(kwarg_handlers) > 0:
        entrance.append(["label", f"{sig.base_method_id}_entry"])

    if check_nonpayable and sig.mutability != "payable":
        # if the contract contains payable functions, but this is not one of them
        # add an assertion that the value of the call is zero
        entrance.append(["assert", ["iszero", "callvalue"]])

    # TODO: handle __init__ and default functions?

    body = [parse_body(c, context) for c in code.body]

    exit = [["label", func_type.exit_sequence_label]]
        + [nonreentrant_post]
        + [["return", "pass", "pass"]] # passed by 

    ret = (["seq"]
            + kwarg_handlers
            + entrance
            + body
            + exit
            )
    if len(kwarg_handlers) > 0:
        ret = ["if", ["eq", tbd_mload_method_id, sig.method_id], ret]

    return LLLnode.from_list(ret, pos=getpos(code))


def generate_lll_for_external_function(
    code: vy_ast.FunctionDef, sig: FunctionSignature, context: Context, check_nonpayable: bool,
) -> LLLnode:
    """
    Parse a external function (FuncDef), and produce full function body.

    :param sig: the FuntionSignature
    :param code: ast of function
    :param check_nonpayable: if True, include a check that `msg.value == 0`
                             at the beginning of the function
    :return: full sig compare & function body
    """

    func_type = code._metadata["type"]

    # Get nonreentrant lock
    nonreentrant_pre, nonreentrant_post = get_nonreentrant_lock(func_type)

    clampers = []

    # Generate copiers
    copier: List[Any] = ["pass"]
    if not len(sig.base_args):
        copier = ["pass"]
    elif sig.name == "__init__":
        copier = ["codecopy", MemoryPositions.RESERVED_MEMORY, "~codelen", sig.base_copy_size]
        context.memory_allocator.expand_memory(sig.max_copy_size)
    clampers.append(copier)

    if check_nonpayable and sig.mutability != "payable":
        # if the contract contains payable functions, but this is not one of them
        # add an assertion that the value of the call is zero
        clampers.append(["assert", ["iszero", "callvalue"]])

    # Fill variable positions
    default_args_start_pos = len(sig.base_args)
    for i, arg in enumerate(sig.args):
        if i < len(sig.base_args):
            clampers.append(
                make_arg_clamper(
                    arg.pos,
                    context.memory_allocator.get_next_memory_position(),
                    arg.typ,
                    sig.name == "__init__",
                )
            )
        if isinstance(arg.typ, ByteArrayLike):
            mem_pos = context.memory_allocator.expand_memory(32 * get_size_of_type(arg.typ))
            context.vars[arg.name] = VariableRecord(arg.name, mem_pos, arg.typ, False)
        else:
            if sig.name == "__init__":
                context.vars[arg.name] = VariableRecord(
                    arg.name, MemoryPositions.RESERVED_MEMORY + arg.pos, arg.typ, False,
                )
            elif i >= default_args_start_pos:  # default args need to be allocated in memory.
                type_size = get_size_of_type(arg.typ) * 32
                default_arg_pos = context.memory_allocator.expand_memory(type_size)
                context.vars[arg.name] = VariableRecord(
                    name=arg.name, pos=default_arg_pos, typ=arg.typ, mutable=False,
                )
            else:
                context.vars[arg.name] = VariableRecord(
                    name=arg.name, pos=4 + arg.pos, typ=arg.typ, mutable=False, location="calldata"
                )

    # Create "clampers" (input well-formedness checkers)
    # Return function body
    if sig.name == "__init__":
        o = LLLnode.from_list(
            ["seq"] + clampers + [parse_body(code.body, context)],  # type: ignore
            pos=getpos(code),
        )
    # Is default function.
    elif sig.is_default_func():
        o = LLLnode.from_list(
            ["seq"] + clampers + [parse_body(code.body, context)] + [["stop"]],  # type: ignore
            pos=getpos(code),
        )
    # Is a normal function.
    else:
        # Function with default parameters.
        if sig.total_default_args > 0:
            function_routine = f"{sig.name}_{sig.method_id}"
            default_sigs = sig_utils.generate_default_arg_sigs(
                code, context.sigs, context.global_ctx
            )
            sig_chain: List[Any] = ["seq"]

            for default_sig in default_sigs:
                sig_compare, _ = get_sig_statements(default_sig, getpos(code))

                # Populate unset default variables
                set_defaults = []
                for arg_name in get_default_names_to_set(sig, default_sig):
                    value = Expr(sig.default_values[arg_name], context).lll_node
                    var = context.vars[arg_name]
                    left = LLLnode.from_list(
                        var.pos,
                        typ=var.typ,
                        location="memory",
                        pos=getpos(code),
                        mutable=var.mutable,
                    )
                    set_defaults.append(make_setter(left, value, "memory", pos=getpos(code)))

                current_sig_arg_names = {x.name for x in default_sig.args}
                base_arg_names = {arg.name for arg in sig.base_args}
                copier_arg_count = len(default_sig.args) - len(sig.base_args)
                copier_arg_names = list(current_sig_arg_names - base_arg_names)

                # Order copier_arg_names, this is very important.
                copier_arg_names = [x.name for x in default_sig.args if x.name in copier_arg_names]

                # Variables to be populated from calldata/stack.
                default_copiers: List[Any] = []
                if copier_arg_count > 0:
                    # Get map of variables in calldata, with thier offsets
                    offset = 4
                    calldata_offset_map = {}
                    for arg in default_sig.args:
                        calldata_offset_map[arg.name] = offset
                        offset += (
                            32
                            if isinstance(arg.typ, ByteArrayLike)
                            else get_size_of_type(arg.typ) * 32
                        )

                    # Copy default parameters from calldata.
                    for arg_name in copier_arg_names:
                        var = context.vars[arg_name]
                        calldata_offset = calldata_offset_map[arg_name]

                        # Add clampers.
                        default_copiers.append(
                            make_arg_clamper(calldata_offset - 4, var.pos, var.typ,)
                        )
                        # Add copying code.
                        _offset: Union[int, List[Any]] = calldata_offset
                        if isinstance(var.typ, ByteArrayLike):
                            _offset = ["add", 4, ["calldataload", calldata_offset]]
                        default_copiers.append(
                            get_external_arg_copier(
                                memory_dest=var.pos, total_size=var.size * 32, offset=_offset,
                            )
                        )

                    default_copiers.append(0)  # for over arching seq, POP

                sig_chain.append(
                    [
                        "if",
                        sig_compare,
                        [
                            "seq",
                            ["seq"] + set_defaults if set_defaults else ["pass"],
                            ["seq_unchecked"] + default_copiers if default_copiers else ["pass"],
                            ["goto", function_routine],
                        ],
                    ]
                )

            # Function with default parameters.
            function_jump_label = f"{sig.name}_{sig.method_id}_skip"
            o = LLLnode.from_list(
                [
                    "seq",
                    sig_chain,
                    [
                        "seq",
                        ["goto", function_jump_label],
                        ["label", function_routine],
                        ["seq"]
                        + nonreentrant_pre
                        + clampers
                        + [parse_body(c, context) for c in code.body]
                        + nonreentrant_post
                        + [["stop"]],
                        ["label", function_jump_label],
                    ],
                ],
                typ=None,
                pos=getpos(code),
            )

        else:
            # Function without default parameters.
            sig_compare, _ = get_sig_statements(sig, getpos(code))
            o = LLLnode.from_list(
                [
                    "if",
                    sig_compare,
                    ["seq"]
                    + nonreentrant_pre
                    + clampers
                    + [parse_body(c, context) for c in code.body]
                    + nonreentrant_post
                    + [["stop"]],
                ],
                typ=None,
                pos=getpos(code),
            )
    return o
