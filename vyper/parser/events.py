from vyper import ast
from vyper.exceptions import (
    InvalidLiteralException,
    TypeMismatchException,
)
from vyper.parser.expr import (
    Expr,
)
from vyper.parser.lll_node import (
    LLLnode,
)
from vyper.parser.parser_utils import (
    base_type_conversion,
    byte_array_to_num,
    getpos,
    make_byte_array_copier,
    make_setter,
    unwrap_location,
)
from vyper.types.types import (
    BaseType,
    ByteArrayLike,
    ListType,
    get_size_of_type,
)
from vyper.utils import (
    bytes_to_int,
    ceil32,
    string_to_bytes,
)


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
                raise TypeMismatchException(
                    "Topic input bytes are too big: %r %r" % (arg_type, expected_type), code_pos
                )
            if isinstance(arg, ast.Str):
                bytez, bytez_length = string_to_bytes(arg.s)
                if len(bytez) > 32:
                    raise InvalidLiteralException(
                        "Can only log a maximum of 32 bytes at a time.", code_pos
                    )
                topics.append(bytes_to_int(bytez + b'\x00' * (32 - bytez_length)))
            else:
                if value.location == "memory":
                    size = ['mload', value]
                elif value.location == "storage":
                    size = ['sload', ['sha3_32', value]]
                topics.append(byte_array_to_num(value, arg, 'uint256', size))
        else:
            value = unwrap_location(value)
            value = base_type_conversion(value, arg_type, expected_type, pos=code_pos)
            topics.append(value)

    return topics


def pack_args_by_32(holder, maxlen, arg, typ, context, placeholder,
                    dynamic_offset_counter=None, datamem_start=None, zero_pad_i=None, pos=None):
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
        holder.append(LLLnode.from_list(['mstore', placeholder, value], typ=typ, location='memory'))
    elif isinstance(typ, ByteArrayLike):

        if isinstance(arg, LLLnode):  # Is prealloacted variable.
            source_lll = arg
        else:
            source_lll = Expr(arg, context).lll_node

        # Set static offset, in arg slot.
        holder.append(LLLnode.from_list(['mstore', placeholder, ['mload', dynamic_offset_counter]]))
        # Get the biginning to write the ByteArray to.
        dest_placeholder = LLLnode.from_list(
            ['add', datamem_start, ['mload', dynamic_offset_counter]],
            typ=typ, location='memory', annotation="pack_args_by_32:dest_placeholder")
        copier = make_byte_array_copier(dest_placeholder, source_lll, pos=pos)
        holder.append(copier)
        # Add zero padding.
        new_maxlen = ceil32(source_lll.typ.maxlen)

        holder.append([
            'with', '_ceil32_end', ['ceil32', ['mload', dest_placeholder]], [
                'seq', ['with', '_bytearray_loc', dest_placeholder, [
                    'seq', ['repeat', zero_pad_i, ['mload', '_bytearray_loc'], new_maxlen, [
                        'seq',
                        # stay within allocated bounds
                        ['if', ['ge', ['mload', zero_pad_i], '_ceil32_end'], 'break'],
                        [
                            'mstore8',
                            ['add', ['add', '_bytearray_loc', 32], ['mload', zero_pad_i]],
                            0,
                        ],
                    ]],
                ]],
            ]
        ])

        # Increment offset counter.
        increment_counter = LLLnode.from_list([
            'mstore', dynamic_offset_counter,
            [
                'add',
                ['add', ['mload', dynamic_offset_counter], ['ceil32', ['mload', dest_placeholder]]],
                32,
            ],
        ], annotation='Increment dynamic offset counter')
        holder.append(increment_counter)
    elif isinstance(typ, ListType):
        maxlen += (typ.count - 1) * 32
        typ = typ.subtype

        def check_list_type_match(provided):  # Check list types match.
            if provided != typ:
                raise TypeMismatchException(
                    "Log list type '%s' does not match provided, expected '%s'" % (provided, typ)
                )

        # List from storage
        if isinstance(arg, ast.Attribute) and arg.value.id == 'self':
            stor_list = context.globals[arg.attr]
            check_list_type_match(stor_list.typ.subtype)
            size = stor_list.typ.count
            mem_offset = 0
            for i in range(0, size):
                storage_offset = i
                arg2 = LLLnode.from_list(
                    ['sload', ['add', ['sha3_32', Expr(arg, context).lll_node], storage_offset]],
                    typ=typ,
                )
                holder, maxlen = pack_args_by_32(
                    holder,
                    maxlen,
                    arg2,
                    typ,
                    context,
                    placeholder + mem_offset,
                    pos=pos,
                )
                mem_offset += get_size_of_type(typ) * 32

        # List from variable.
        elif isinstance(arg, ast.Name):
            size = context.vars[arg.id].size
            pos = context.vars[arg.id].pos
            check_list_type_match(context.vars[arg.id].typ.subtype)
            mem_offset = 0
            for _ in range(0, size):
                arg2 = LLLnode.from_list(pos + mem_offset, typ=typ, location='memory')
                holder, maxlen = pack_args_by_32(
                    holder,
                    maxlen,
                    arg2,
                    typ,
                    context,
                    placeholder + mem_offset,
                    pos=pos,
                )
                mem_offset += get_size_of_type(typ) * 32

        # List from list literal.
        else:
            mem_offset = 0
            for arg2 in arg.elts:
                holder, maxlen = pack_args_by_32(
                    holder,
                    maxlen,
                    arg2,
                    typ,
                    context,
                    placeholder + mem_offset,
                    pos=pos,
                )
                mem_offset += get_size_of_type(typ) * 32
    return holder, maxlen


# Pack logging data arguments
def pack_logging_data(expected_data, args, context, pos):
    # Checks to see if there's any data
    if not args:
        return ['seq'], 0, None, 0
    holder = ['seq']
    maxlen = len(args) * 32  # total size of all packed args (upper limit)

    # Unroll any function calls, to temp variables.
    prealloacted = {}
    for idx, (arg, _expected_arg) in enumerate(zip(args, expected_data)):

        if isinstance(arg, (ast.Str, ast.Call)):
            expr = Expr(arg, context)
            source_lll = expr.lll_node
            typ = source_lll.typ

            if isinstance(arg, ast.Str):
                if len(arg.s) > typ.maxlen:
                    raise TypeMismatchException(
                        "Data input bytes are to big: %r %r" % (len(arg.s), typ), pos
                    )

            tmp_variable = context.new_variable(
                '_log_pack_var_%i_%i' % (arg.lineno, arg.col_offset),
                source_lll.typ,
            )
            tmp_variable_node = LLLnode.from_list(
                tmp_variable,
                typ=source_lll.typ,
                pos=getpos(arg),
                location="memory",
                annotation='log_prealloacted %r' % source_lll.typ,
            )
            # Store len.
            # holder.append(['mstore', len_placeholder, ['mload', unwrap_location(source_lll)]])
            # Copy bytes.

            holder.append(
                make_setter(tmp_variable_node, source_lll, pos=getpos(arg), location='memory')
            )
            prealloacted[idx] = tmp_variable_node

    requires_dynamic_offset = any([isinstance(data.typ, ByteArrayLike) for data in expected_data])
    if requires_dynamic_offset:
        # Iterator used to zero pad memory.
        zero_pad_i = context.new_placeholder(BaseType('uint256'))
        dynamic_offset_counter = context.new_placeholder(BaseType(32))
        dynamic_placeholder = context.new_placeholder(BaseType(32))
    else:
        dynamic_offset_counter = None
        zero_pad_i = None

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
                holder,
                maxlen,
                prealloacted.get(i, arg),
                typ,
                context,
                placeholder,
                zero_pad_i=zero_pad_i,
                pos=pos,
            )

    # Dynamic position starts right after the static args.
    if requires_dynamic_offset:
        holder.append(LLLnode.from_list(['mstore', dynamic_offset_counter, maxlen]))

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
                zero_pad_i=zero_pad_i,
                pos=pos
            )

    return holder, maxlen, dynamic_offset_counter, datamem_start
