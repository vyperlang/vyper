from typing import Any, List

from vyper import ast as vy_ast
from vyper.ast.signatures import FunctionSignature, sig_utils
from vyper.ast.signatures.function_signature import VariableRecord
from vyper.old_codegen.context import Context
from vyper.old_codegen.expr import Expr
from vyper.old_codegen.function_definitions.utils import (
    get_default_names_to_set,
    get_nonreentrant_lock,
    get_sig_statements,
    make_unpacker,
)
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import getpos, make_setter
from vyper.old_codegen.stmt import parse_body
from vyper.old_codegen.types.types import (
    BaseType,
    ByteArrayLike,
    get_size_of_type,
)
from vyper.utils import MemoryPositions


def get_internal_arg_copier(total_size: int, memory_dest: int) -> List[Any]:
    """
    Copy arguments.
    For internal functions, MSTORE arguments and callback pointer from the stack.

    :param  total_size: total size to copy
    :param  memory_dest: base memory position to copy to
    :return: LLL list that copies total_size of memory
    """

    copier: List[Any] = ["seq"]
    for pos in range(0, total_size, 32):
        copier.append(["mstore", memory_dest + pos, "pass"])
    return copier


def parse_internal_function(
    code: vy_ast.FunctionDef, sig: FunctionSignature, context: Context
) -> LLLnode:
    """
    Parse a internal function (FuncDef), and produce full function body.

    :param sig: the FuntionSignature
    :param code: ast of function
    :return: full sig compare & function body
    """

    func_type = code._metadata["type"]

    # Get nonreentrant lock
    nonreentrant_pre, nonreentrant_post = get_nonreentrant_lock(func_type)

    # Create callback_ptr, this stores a destination in the bytecode for a internal
    # function to jump to after a function has executed.
    clampers: List[LLLnode] = []

    # Allocate variable space.
    context.memory_allocator.expand_memory(sig.max_copy_size)

    _post_callback_ptr = f"{sig.name}_{sig.method_id}_post_callback_ptr"
    context.callback_ptr = context.new_internal_variable(typ=BaseType("uint256"))
    clampers.append(
        LLLnode.from_list(
            ["mstore", context.callback_ptr, "pass"], annotation="pop callback pointer",
        )
    )
    if sig.total_default_args > 0:
        clampers.append(LLLnode.from_list(["label", _post_callback_ptr]))

    # internal functions without return types need to jump back to
    # the calling function, as there is no return statement to handle the
    # jump.
    if sig.output_type is None:
        stop_func = [["jump", ["mload", context.callback_ptr]]]
    else:
        stop_func = [["stop"]]

    # Generate copiers
    if len(sig.base_args) == 0:
        copier = ["pass"]
        clampers.append(LLLnode.from_list(copier))
    elif sig.total_default_args == 0:
        copier = get_internal_arg_copier(
            total_size=sig.base_copy_size, memory_dest=MemoryPositions.RESERVED_MEMORY
        )
        clampers.append(LLLnode.from_list(copier))

    # Fill variable positions
    for arg in sig.args:
        if isinstance(arg.typ, ByteArrayLike):
            mem_pos = context.memory_allocator.expand_memory(32 * get_size_of_type(arg.typ))
            context.vars[arg.name] = VariableRecord(arg.name, mem_pos, arg.typ, False)
        else:
            context.vars[arg.name] = VariableRecord(
                arg.name, MemoryPositions.RESERVED_MEMORY + arg.pos, arg.typ, False,
            )

    # internal function copiers. No clamping for internal functions.
    dyn_variable_names = [a.name for a in sig.base_args if isinstance(a.typ, ByteArrayLike)]
    if dyn_variable_names:
        i_placeholder = context.new_internal_variable(typ=BaseType("uint256"))
        unpackers: List[Any] = []
        for idx, var_name in enumerate(dyn_variable_names):
            var = context.vars[var_name]
            ident = f"_load_args_{sig.method_id}_dynarg{idx}"
            o = make_unpacker(ident=ident, i_placeholder=i_placeholder, begin_pos=var.pos)
            unpackers.append(o)

        if not unpackers:
            unpackers = ["pass"]

        # 0 added to complete full overarching 'seq' statement, see internal_label.
        unpackers.append(0)
        clampers.append(
            LLLnode.from_list(
                ["seq_unchecked"] + unpackers,
                typ=None,
                annotation="dynamic unpacker",
                pos=getpos(code),
            )
        )

    # Function has default arguments.
    if sig.total_default_args > 0:  # Function with default parameters.

        default_sigs = sig_utils.generate_default_arg_sigs(code, context.sigs, context.global_ctx)
        sig_chain: List[Any] = ["seq"]

        for default_sig in default_sigs:
            sig_compare, internal_label = get_sig_statements(default_sig, getpos(code))

            # Populate unset default variables
            set_defaults = []
            for arg_name in get_default_names_to_set(sig, default_sig):
                value = Expr(sig.default_values[arg_name], context).lll_node
                var = context.vars[arg_name]
                left = LLLnode.from_list(
                    var.pos, typ=var.typ, location="memory", pos=getpos(code), mutable=var.mutable
                )
                set_defaults.append(make_setter(left, value, "memory", pos=getpos(code)))
            current_sig_arg_names = [x.name for x in default_sig.args]

            # Load all variables in default section, if internal,
            # because the stack is a linear pipe.
            copier_arg_count = len(default_sig.args)
            copier_arg_names = current_sig_arg_names

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
                        32 if isinstance(arg.typ, ByteArrayLike) else get_size_of_type(arg.typ) * 32
                    )

                # Copy set default parameters from calldata
                dynamics = []
                for arg_name in copier_arg_names:
                    var = context.vars[arg_name]
                    if isinstance(var.typ, ByteArrayLike):
                        _size = 32
                        dynamics.append(var.pos)
                    else:
                        _size = var.size * 32
                    default_copiers.append(
                        get_internal_arg_copier(memory_dest=var.pos, total_size=_size,)
                    )

                # Unpack byte array if necessary.
                if dynamics:
                    i_placeholder = context.new_internal_variable(typ=BaseType("uint256"))
                    for idx, var_pos in enumerate(dynamics):
                        ident = f"unpack_default_sig_dyn_{default_sig.method_id}_arg{idx}"
                        default_copiers.append(
                            make_unpacker(
                                ident=ident, i_placeholder=i_placeholder, begin_pos=var_pos,
                            )
                        )
                default_copiers.append(0)  # for over arching seq, POP

            sig_chain.append(
                [
                    "if",
                    sig_compare,
                    [
                        "seq",
                        internal_label,
                        LLLnode.from_list(
                            ["mstore", context.callback_ptr, "pass"],
                            annotation="pop callback pointer",
                            pos=getpos(code),
                        ),
                        ["seq"] + set_defaults if set_defaults else ["pass"],
                        ["seq_unchecked"] + default_copiers if default_copiers else ["pass"],
                        ["goto", _post_callback_ptr],
                    ],
                ]
            )

        # With internal functions all variable loading occurs in the default
        # function sub routine.
        _clampers = [["label", _post_callback_ptr]]

        # Function with default parameters.
        return LLLnode.from_list(
            [
                "seq",
                sig_chain,
                ["seq"]
                + nonreentrant_pre
                + _clampers
                + [parse_body(c, context) for c in code.body]
                + nonreentrant_post
                + stop_func,
            ],
            typ=None,
            pos=getpos(code),
        )

    else:
        # Function without default parameters.
        sig_compare, internal_label = get_sig_statements(sig, getpos(code))
        return LLLnode.from_list(
            ["seq"]
            + [internal_label]
            + nonreentrant_pre
            + clampers
            + [parse_body(c, context) for c in code.body]
            + nonreentrant_post
            + stop_func,
            typ=None,
            pos=getpos(code),
        )
