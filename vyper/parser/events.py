from vyper import ast as vy_ast
from vyper.exceptions import TypeMismatch
from vyper.parser.expr import Expr
from vyper.parser.lll_node import LLLnode
from vyper.parser.parser_utils import (
    base_type_conversion,
    getpos,
    make_byte_array_copier,
    make_setter,
    unwrap_location,
    zero_pad,
)
from vyper.types.types import (
    BaseType,
    ByteArrayLike,
    ListType,
    get_size_of_type,
)
from vyper.utils import bytes_to_int, ceil32, keccak256


def pack_logging_topics(event_id, args, expected_topics, context, pos):
    topics = [event_id]
    code_pos = pos
    for pos, expected_topic in enumerate(expected_topics):
        expected_type = expected_topic.typ
        arg = args[pos]
        value = Expr(arg, context).lll_node
        arg_type = value.typ

        if isinstance(arg_type, ByteArrayLike) and isinstance(expected_type, ByteArrayLike):
            if arg_type.maxlen > expected_type.maxlen:
                raise TypeMismatch(
                    f"Topic input bytes are too big: {arg_type} {expected_type}", code_pos
                )

            if isinstance(arg, (vy_ast.Str, vy_ast.Bytes)):
                # for literals, generate the topic at compile time
                value = arg.value
                if isinstance(value, str):
                    value = value.encode()
                topics.append(bytes_to_int(keccak256(value)))

            elif value.location == "memory":
                topics.append(["sha3", ["add", value, 32], ["mload", value]])

            else:
                # storage or calldata
                placeholder = context.new_placeholder(value.typ)
                placeholder_node = LLLnode.from_list(placeholder, typ=value.typ, location="memory")
                copier = make_byte_array_copier(
                    placeholder_node,
                    LLLnode.from_list("_sub", typ=value.typ, location=value.location),
                )
                lll_node = [
                    "with",
                    "_sub",
                    value,
                    ["seq", copier, ["sha3", ["add", placeholder, 32], ["mload", placeholder]]],
                ]
                topics.append(lll_node)

        elif isinstance(arg_type, ListType) and isinstance(expected_type, ListType):
            size = get_size_of_type(value.typ) * 32
            if value.location == "memory":
                topics.append(["sha3", value, size])

            else:
                # storage or calldata
                placeholder = context.new_placeholder(value.typ)
                placeholder_node = LLLnode.from_list(placeholder, typ=value.typ, location="memory")
                setter = make_setter(placeholder_node, value, "memory", value.pos)
                lll_node = ["seq", setter, ["sha3", placeholder, size]]
                topics.append(lll_node)

        else:
            if arg_type != expected_type:
                raise TypeMismatch(
                    f"Invalid type for logging topic, got {arg_type} expected {expected_type}",
                    value.pos,
                )
            value = unwrap_location(value)
            value = base_type_conversion(value, arg_type, expected_type, pos=code_pos)
            topics.append(value)

    return topics


def pack_args_by_32(
    holder,
    maxlen,
    arg,
    typ,
    context,
    placeholder,
    dynamic_offset_counter=None,
    datamem_start=None,
    pos=None,
):
    """
    Copy necessary variables to pre-allocated memory section.

    :param holder: Complete holder for all args
    :param maxlen: Total length in bytes of the full arg section (static + dynamic).
    :param arg: Current arg to pack
    :param context: Context of arg
    :param placeholder: Static placeholder for static argument part.
    :param dynamic_offset_counter: position counter stored in static args.
    :param dynamic_placeholder: pointer to current position in memory to write dynamic values to.
    :param datamem_start: position where the whole datemem section starts.
    """

    if isinstance(typ, BaseType):
        if isinstance(arg, LLLnode):
            value = unwrap_location(arg)
        else:
            value = Expr(arg, context).lll_node
            value = base_type_conversion(value, value.typ, typ, pos)
        holder.append(LLLnode.from_list(["mstore", placeholder, value], typ=typ, location="memory"))
    elif isinstance(typ, ByteArrayLike):

        if isinstance(arg, LLLnode):  # Is prealloacted variable.
            source_lll = arg
        else:
            source_lll = Expr(arg, context).lll_node

        # Set static offset, in arg slot.
        holder.append(LLLnode.from_list(["mstore", placeholder, ["mload", dynamic_offset_counter]]))
        # Get the biginning to write the ByteArray to.
        dest_placeholder = LLLnode.from_list(
            ["add", datamem_start, ["mload", dynamic_offset_counter]],
            typ=typ,
            location="memory",
            annotation="pack_args_by_32:dest_placeholder",
        )
        copier = make_byte_array_copier(dest_placeholder, source_lll, pos=pos)
        holder.append(copier)
        # Add zero padding.
        holder.append(zero_pad(dest_placeholder))

        # Increment offset counter.
        increment_counter = LLLnode.from_list(
            [
                "mstore",
                dynamic_offset_counter,
                [
                    "add",
                    [
                        "add",
                        ["mload", dynamic_offset_counter],
                        ["ceil32", ["mload", dest_placeholder]],
                    ],
                    32,
                ],
            ],
            annotation="Increment dynamic offset counter",
        )
        holder.append(increment_counter)
    elif isinstance(typ, ListType):
        maxlen += (typ.count - 1) * 32
        typ = typ.subtype

        def check_list_type_match(provided):  # Check list types match.
            if provided != typ:
                raise TypeMismatch(
                    f"Log list type '{provided}' does not match provided, expected '{typ}'"
                )

        # NOTE: Below code could be refactored into iterators/getter functions for each type of
        #       repetitive loop. But seeing how each one is a unique for loop, and in which way
        #       the sub value makes the difference in each type of list clearer.

        # List from storage
        if isinstance(arg, vy_ast.Attribute) and arg.value.id == "self":
            stor_list = context.globals[arg.attr]
            check_list_type_match(stor_list.typ.subtype)
            size = stor_list.typ.count
            mem_offset = 0
            for i in range(0, size):
                storage_offset = i
                arg2 = LLLnode.from_list(
                    ["sload", ["add", ["sha3_32", Expr(arg, context).lll_node], storage_offset]],
                    typ=typ,
                )
                holder, maxlen = pack_args_by_32(
                    holder, maxlen, arg2, typ, context, placeholder + mem_offset, pos=pos,
                )
                mem_offset += get_size_of_type(typ) * 32

        # List from variable.
        elif isinstance(arg, vy_ast.Name):
            size = context.vars[arg.id].size
            pos = context.vars[arg.id].pos
            check_list_type_match(context.vars[arg.id].typ.subtype)
            mem_offset = 0
            for _ in range(0, size):
                arg2 = LLLnode.from_list(
                    pos + mem_offset, typ=typ, location=context.vars[arg.id].location
                )
                holder, maxlen = pack_args_by_32(
                    holder, maxlen, arg2, typ, context, placeholder + mem_offset, pos=pos,
                )
                mem_offset += get_size_of_type(typ) * 32

        # List from list literal.
        else:
            mem_offset = 0
            for arg2 in arg.elements:
                holder, maxlen = pack_args_by_32(
                    holder, maxlen, arg2, typ, context, placeholder + mem_offset, pos=pos,
                )
                mem_offset += get_size_of_type(typ) * 32
    return holder, maxlen


# Pack logging data arguments
def pack_logging_data(expected_data, args, context, pos):
    # Checks to see if there's any data
    if not args:
        return ["seq"], 0, None, 0
    holder = ["seq"]
    maxlen = len(args) * 32  # total size of all packed args (upper limit)

    # Unroll any function calls, to temp variables.
    prealloacted = {}
    for idx, (arg, _expected_arg) in enumerate(zip(args, expected_data)):

        if isinstance(arg, (vy_ast.Str, vy_ast.Call)):
            expr = Expr(arg, context)
            source_lll = expr.lll_node
            typ = source_lll.typ

            if isinstance(arg, vy_ast.Str):
                if len(arg.s) > typ.maxlen:
                    raise TypeMismatch(f"Data input bytes are to big: {len(arg.s)} {typ}", pos)

            tmp_variable = context.new_internal_variable(
                f"_log_pack_var_{arg.lineno}_{arg.col_offset}", source_lll.typ,
            )
            tmp_variable_node = LLLnode.from_list(
                tmp_variable,
                typ=source_lll.typ,
                pos=getpos(arg),
                location="memory",
                annotation=f"log_prealloacted {source_lll.typ}",
            )
            # Store len.
            # holder.append(['mstore', len_placeholder, ['mload', unwrap_location(source_lll)]])
            # Copy bytes.

            holder.append(
                make_setter(tmp_variable_node, source_lll, pos=getpos(arg), location="memory")
            )
            prealloacted[idx] = tmp_variable_node

    requires_dynamic_offset = any([isinstance(data.typ, ByteArrayLike) for data in expected_data])
    if requires_dynamic_offset:
        dynamic_offset_counter = context.new_placeholder(BaseType(32))
        dynamic_placeholder = context.new_placeholder(BaseType(32))
    else:
        dynamic_offset_counter = None

    # Create placeholder for static args. Note: order of new_*() is important.
    placeholder_map = {}
    for i, (_arg, data) in enumerate(zip(args, expected_data)):
        typ = data.typ
        if not isinstance(typ, ByteArrayLike):
            placeholder = context.new_placeholder(typ)
        else:
            placeholder = context.new_placeholder(BaseType(32))
        placeholder_map[i] = placeholder

    # Populate static placeholders.
    for i, (arg, data) in enumerate(zip(args, expected_data)):
        typ = data.typ
        placeholder = placeholder_map[i]
        if not isinstance(typ, ByteArrayLike):
            holder, maxlen = pack_args_by_32(
                holder, maxlen, prealloacted.get(i, arg), typ, context, placeholder, pos=pos,
            )

    # Dynamic position starts right after the static args.
    if requires_dynamic_offset:
        holder.append(LLLnode.from_list(["mstore", dynamic_offset_counter, maxlen]))

    # Calculate maximum dynamic offset placeholders, used for gas estimation.
    for _arg, data in zip(args, expected_data):
        typ = data.typ
        if isinstance(typ, ByteArrayLike):
            maxlen += 32 + ceil32(typ.maxlen)

    if requires_dynamic_offset:
        datamem_start = dynamic_placeholder + 32
    else:
        datamem_start = placeholder_map[0]

    # Copy necessary data into allocated dynamic section.
    for i, (arg, data) in enumerate(zip(args, expected_data)):
        typ = data.typ
        if isinstance(typ, ByteArrayLike):
            pack_args_by_32(
                holder=holder,
                maxlen=maxlen,
                arg=prealloacted.get(i, arg),
                typ=typ,
                context=context,
                placeholder=placeholder_map[i],
                datamem_start=datamem_start,
                dynamic_offset_counter=dynamic_offset_counter,
                pos=pos,
            )

    return holder, maxlen, dynamic_offset_counter, datamem_start
