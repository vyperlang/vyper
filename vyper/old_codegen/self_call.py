import itertools

from vyper.ast.signatures.function_signature import FunctionSignature
from vyper.exceptions import (
    StateAccessViolation,
    StructureException,
    TypeCheckFailure,
)
from vyper.old_codegen.abi import abi_decode
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import getpos, pack_arguments
from vyper.old_codegen.types import (
    BaseType,
    ByteArrayLike,
    ListType,
    TupleLike,
    get_size_of_type,
    get_static_size_of_type,
    has_dynamic_data,
)


def _call_make_placeholder(stmt_expr, context, sig):
    if sig.output_type is None:
        return 0, 0, 0

    output_placeholder = context.new_internal_variable(typ=sig.output_type)
    output_size = get_size_of_type(sig.output_type) * 32

    if isinstance(sig.output_type, BaseType):
        returner = output_placeholder
    elif isinstance(sig.output_type, ByteArrayLike):
        returner = output_placeholder
    elif isinstance(sig.output_type, TupleLike):
        # incase of struct we need to decode the output and then return it
        returner = ["seq"]
        decoded_placeholder = context.new_internal_variable(typ=sig.output_type)
        decoded_node = LLLnode(decoded_placeholder, typ=sig.output_type, location="memory")
        output_node = LLLnode(output_placeholder, typ=sig.output_type, location="memory")
        returner.append(abi_decode(decoded_node, output_node))
        returner.extend([decoded_placeholder])
    elif isinstance(sig.output_type, ListType):
        returner = output_placeholder
    else:
        raise TypeCheckFailure(f"Invalid output type: {sig.output_type}")
    return output_placeholder, returner, output_size


def make_call(stmt_expr, context):
    # ** Internal Call **
    # Steps:
    # (x) push current local variables
    # (x) push arguments
    # (x) push jumpdest (callback ptr)
    # (x) jump to label
    # (x) pop return values
    # (x) pop local variables

    pop_local_vars = []
    push_local_vars = []
    pop_return_values = []
    push_args = []
    method_name = stmt_expr.func.attr

    # TODO check this out
    from vyper.old_codegen.expr import parse_sequence

    pre_init, expr_args = parse_sequence(stmt_expr, stmt_expr.args, context)
    sig = FunctionSignature.lookup_sig(context.sigs, method_name, expr_args, stmt_expr, context,)

    if context.is_constant() and sig.mutability not in ("view", "pure"):
        raise StateAccessViolation(
            f"May not call state modifying function "
            f"'{method_name}' within {context.pp_constancy()}.",
            getpos(stmt_expr),
        )

    if not sig.internal:
        raise StructureException("Cannot call external functions via 'self'", stmt_expr)

    # Push local variables.
    var_slots = [(v.pos, v.size) for name, v in context.vars.items() if v.location == "memory"]
    if var_slots:
        var_slots.sort(key=lambda x: x[0])

        if len(var_slots) > 10:
            # if memory is large enough, push and pop it via iteration
            mem_from, mem_to = var_slots[0][0], var_slots[-1][0] + var_slots[-1][1] * 32
            i_placeholder = context.new_internal_variable(BaseType("uint256"))
            local_save_ident = f"_{stmt_expr.lineno}_{stmt_expr.col_offset}"
            push_loop_label = "save_locals_start" + local_save_ident
            pop_loop_label = "restore_locals_start" + local_save_ident
            push_local_vars = [
                ["mstore", i_placeholder, mem_from],
                ["label", push_loop_label],
                ["mload", ["mload", i_placeholder]],
                ["mstore", i_placeholder, ["add", ["mload", i_placeholder], 32]],
                ["if", ["lt", ["mload", i_placeholder], mem_to], ["goto", push_loop_label]],
            ]
            pop_local_vars = [
                ["mstore", i_placeholder, mem_to - 32],
                ["label", pop_loop_label],
                ["mstore", ["mload", i_placeholder], "pass"],
                ["mstore", i_placeholder, ["sub", ["mload", i_placeholder], 32]],
                ["if", ["ge", ["mload", i_placeholder], mem_from], ["goto", pop_loop_label]],
            ]
        else:
            # for smaller memory, hardcode the mload/mstore locations
            push_mem_slots = []
            for pos, size in var_slots:
                push_mem_slots.extend([pos + i * 32 for i in range(size)])

            push_local_vars = [["mload", pos] for pos in push_mem_slots]
            pop_local_vars = [["mstore", pos, "pass"] for pos in push_mem_slots[::-1]]

    # Push Arguments
    if expr_args:
        inargs, inargsize, arg_pos = pack_arguments(
            sig, expr_args, context, stmt_expr, is_external_call=False
        )
        push_args += [inargs]  # copy arguments first, to not mess up the push/pop sequencing.

        static_arg_size = 32 * sum([get_static_size_of_type(arg.typ) for arg in expr_args])
        static_pos = int(arg_pos + static_arg_size)
        needs_dyn_section = any([has_dynamic_data(arg.typ) for arg in expr_args])

        if needs_dyn_section:
            ident = f"push_args_{sig.method_id}_{stmt_expr.lineno}_{stmt_expr.col_offset}"
            start_label = ident + "_start"
            end_label = ident + "_end"
            i_placeholder = context.new_internal_variable(BaseType("uint256"))

            # Calculate copy start position.
            # Given | static | dynamic | section in memory,
            # copy backwards so the values are in order on the stack.
            # We calculate i, the end of the whole encoded part
            # (i.e. the starting index for copy)
            # by taking ceil32(len<arg>) + offset<arg> + arg_pos
            # for the last dynamic argument and arg_pos is the start
            # the whole argument section.
            idx = 0
            for arg in expr_args:
                if isinstance(arg.typ, ByteArrayLike):
                    last_idx = idx
                idx += get_static_size_of_type(arg.typ)
            push_args += [
                [
                    "with",
                    "offset",
                    ["mload", arg_pos + last_idx * 32],
                    [
                        "with",
                        "len_pos",
                        ["add", arg_pos, "offset"],
                        [
                            "with",
                            "len_value",
                            ["mload", "len_pos"],
                            ["mstore", i_placeholder, ["add", "len_pos", ["ceil32", "len_value"]]],
                        ],
                    ],
                ]
            ]
            # loop from end of dynamic section to start of dynamic section,
            # pushing each element onto the stack.
            push_args += [
                ["label", start_label],
                ["if", ["lt", ["mload", i_placeholder], static_pos], ["goto", end_label]],
                ["mload", ["mload", i_placeholder]],
                ["mstore", i_placeholder, ["sub", ["mload", i_placeholder], 32]],  # decrease i
                ["goto", start_label],
                ["label", end_label],
            ]

        # push static section
        push_args += [["mload", pos] for pos in reversed(range(arg_pos, static_pos, 32))]
    elif sig.args:
        raise StructureException(
            f"Wrong number of args for: {sig.name} (0 args given, expected {len(sig.args)})",
            stmt_expr,
        )

    # Jump to function label.
    jump_to_func = [
        ["add", ["pc"], 6],  # set callback pointer.
        ["goto", f"priv_{sig.method_id}"],
        ["jumpdest"],
    ]

    # Pop return values.
    returner = [0]
    if sig.output_type:
        output_placeholder, returner, output_size = _call_make_placeholder(stmt_expr, context, sig)
        if output_size > 0:
            dynamic_offsets = []
            if isinstance(sig.output_type, (BaseType, ListType)):
                pop_return_values = [
                    ["mstore", ["add", output_placeholder, pos], "pass"]
                    for pos in range(0, output_size, 32)
                ]
            elif isinstance(sig.output_type, ByteArrayLike):
                dynamic_offsets = [(0, sig.output_type)]
                pop_return_values = [
                    ["pop", "pass"],
                ]
            elif isinstance(sig.output_type, TupleLike):
                static_offset = 0
                pop_return_values = []
                for name, typ in sig.output_type.tuple_items():
                    if isinstance(typ, ByteArrayLike):
                        pop_return_values.append(
                            ["mstore", ["add", output_placeholder, static_offset], "pass"]
                        )
                        dynamic_offsets.append(
                            (["mload", ["add", output_placeholder, static_offset]], name)
                        )
                        static_offset += 32
                    else:
                        member_output_size = get_size_of_type(typ) * 32
                        pop_return_values.extend(
                            [
                                ["mstore", ["add", output_placeholder, pos], "pass"]
                                for pos in range(
                                    static_offset, static_offset + member_output_size, 32
                                )
                            ]
                        )
                        static_offset += member_output_size

            # append dynamic unpacker.
            dyn_idx = 0
            for in_memory_offset, _out_type in dynamic_offsets:
                ident = f"{stmt_expr.lineno}_{stmt_expr.col_offset}_arg_{dyn_idx}"
                dyn_idx += 1
                start_label = "dyn_unpack_start_" + ident
                end_label = "dyn_unpack_end_" + ident
                i_placeholder = context.new_internal_variable(typ=BaseType("uint256"))
                begin_pos = ["add", output_placeholder, in_memory_offset]
                # loop until length.
                o = LLLnode.from_list(
                    [
                        "seq_unchecked",
                        ["mstore", begin_pos, "pass"],  # get len
                        ["mstore", i_placeholder, 0],
                        ["label", start_label],
                        [  # break
                            "if",
                            ["ge", ["mload", i_placeholder], ["ceil32", ["mload", begin_pos]]],
                            ["goto", end_label],
                        ],
                        [  # pop into correct memory slot.
                            "mstore",
                            ["add", ["add", begin_pos, 32], ["mload", i_placeholder]],
                            "pass",
                        ],
                        # increment i
                        ["mstore", i_placeholder, ["add", 32, ["mload", i_placeholder]]],
                        ["goto", start_label],
                        ["label", end_label],
                    ],
                    typ=None,
                    annotation="dynamic unpacker",
                    pos=getpos(stmt_expr),
                )
                pop_return_values.append(o)

    call_body = list(
        itertools.chain(
            ["seq_unchecked"],
            pre_init,
            push_local_vars,
            push_args,
            jump_to_func,
            pop_return_values,
            pop_local_vars,
            [returner],
        )
    )
    # If we have no return, we need to pop off
    pop_returner_call_body = ["pop", call_body] if sig.output_type is None else call_body

    o = LLLnode.from_list(
        pop_returner_call_body,
        typ=sig.output_type,
        location="memory",
        pos=getpos(stmt_expr),
        annotation=f"Internal Call: {method_name}",
        add_gas_estimate=sig.gas,
    )
    o.gas += sig.gas
    return o
