from vyper import ast as vy_ast
from vyper.exceptions import StructureException
from vyper.old_codegen.expr import Expr
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import (
    getpos,
    make_byte_array_copier,
    make_setter,
    mzero,
    unwrap_location,
    zero_pad,
)
from vyper.old_codegen.types.types import BaseType, ByteArrayLike
from vyper.semantics.types.abstract import ArrayValueAbstractType
from vyper.semantics.types.indexable.sequence import ArrayDefinition
from vyper.semantics.types.value.numeric import Uint256Definition
from vyper.utils import bytes_to_int, keccak256


def pack_logging_topics(event_id, arg_nodes, arg_types, context):
    topics = [event_id]
    for node, typ in zip(arg_nodes, arg_types):
        value = Expr(node, context).lll_node

        if isinstance(typ, ArrayValueAbstractType):
            if isinstance(node, (vy_ast.Str, vy_ast.Bytes)):
                # for literals, generate the topic at compile time
                value = node.value
                if isinstance(value, str):
                    value = value.encode()
                topics.append(bytes_to_int(keccak256(value)))

            elif value.location == "memory":
                topics.append(["sha3", ["add", value, 32], ["mload", value]])

            else:
                # storage or calldata
                placeholder = context.new_internal_variable(value.typ)
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

        elif isinstance(typ, ArrayDefinition):
            size = typ.size_in_bytes
            if value.location == "memory":
                topics.append(["sha3", value, size])

            else:
                # storage or calldata
                placeholder = context.new_internal_variable(value.typ)
                placeholder_node = LLLnode.from_list(placeholder, typ=value.typ, location="memory")
                setter = make_setter(placeholder_node, value, "memory", value.pos)
                lll_node = ["seq", setter, ["sha3", placeholder, size]]
                topics.append(lll_node)

        else:
            value = unwrap_location(value)
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

    if typ.size_in_bytes == 32:
        if isinstance(arg, LLLnode):
            value = unwrap_location(arg)
        else:
            value = Expr(arg, context).lll_node
            value = unwrap_location(value)
        holder.append(LLLnode.from_list(["mstore", placeholder, value], location="memory"))
    elif isinstance(typ, ArrayValueAbstractType):

        if isinstance(arg, LLLnode):  # Is prealloacted variable.
            source_lll = arg
        else:
            source_lll = Expr(arg, context).lll_node

        # Set static offset, in arg slot.
        holder.append(LLLnode.from_list(["mstore", placeholder, ["mload", dynamic_offset_counter]]))
        # Get the beginning to write the ByteArray to.
        # TODO refactor out the use of `ByteArrayLike` once old types are removed from parser
        dest_placeholder = LLLnode.from_list(
            ["add", datamem_start, ["mload", dynamic_offset_counter]],
            typ=ByteArrayLike(typ.length),
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
    elif isinstance(typ, ArrayDefinition):

        if isinstance(arg, vy_ast.Call) and arg.func.get("id") == "empty":
            # special case for `empty()` with a static-sized array
            holder.append(mzero(placeholder, typ.size_in_bytes))
            maxlen += typ.size_in_bytes - 32
            return holder, maxlen

        maxlen += (typ.length - 1) * 32
        typ = typ.value_type

        # NOTE: Below code could be refactored into iterators/getter functions for each type of
        #       repetitive loop. But seeing how each one is a unique for loop, and in which way
        #       the sub value makes the difference in each type of list clearer.

        # List from storage
        if isinstance(arg, vy_ast.Attribute) and arg.value.id == "self":
            stor_list = context.globals[arg.attr]
            size = stor_list.typ.count
            mem_offset = 0
            for i in range(0, size):
                storage_offset = i
                arg2 = LLLnode.from_list(
                    ["sload", ["add", Expr(arg, context).lll_node, storage_offset]],
                )
                holder, maxlen = pack_args_by_32(
                    holder, maxlen, arg2, typ, context, placeholder + mem_offset, pos=pos,
                )
                mem_offset += typ.size_in_bytes

        # List from variable.
        elif isinstance(arg, vy_ast.Name):
            size = context.vars[arg.id].size
            pos = context.vars[arg.id].pos
            mem_offset = 0
            for _ in range(0, size):
                arg2 = LLLnode.from_list(pos + mem_offset, location=context.vars[arg.id].location)
                holder, maxlen = pack_args_by_32(
                    holder, maxlen, arg2, typ, context, placeholder + mem_offset, pos=pos,
                )
                mem_offset += typ.size_in_bytes

        # List from list literal.
        else:
            mem_offset = 0
            for arg2 in arg.elements:
                holder, maxlen = pack_args_by_32(
                    holder, maxlen, arg2, typ, context, placeholder + mem_offset, pos=pos,
                )
                mem_offset += typ.size_in_bytes
    return holder, maxlen


# Pack logging data arguments
def pack_logging_data(arg_nodes, arg_types, context, pos):
    # Checks to see if there's any data
    if not arg_nodes:
        return ["seq"], 0, None, 0
    holder = ["seq"]
    maxlen = len(arg_nodes) * 32  # total size of all packed args (upper limit)

    # Unroll any function calls, to temp variables.
    prealloacted = {}
    for idx, node in enumerate(arg_nodes):

        if isinstance(node, (vy_ast.Str, vy_ast.Call)) and node.get("func.id") != "empty":
            expr = Expr(node, context)
            source_lll = expr.lll_node
            tmp_variable = context.new_internal_variable(source_lll.typ)
            tmp_variable_node = LLLnode.from_list(
                tmp_variable,
                typ=source_lll.typ,
                pos=getpos(node),
                location="memory",
                annotation=f"log_prealloacted {source_lll.typ}",
            )
            # Copy bytes.
            holder.append(
                make_setter(tmp_variable_node, source_lll, pos=getpos(node), location="memory")
            )
            prealloacted[idx] = tmp_variable_node

    # Create internal variables for for dynamic and static args.
    static_types = []
    for typ in arg_types:
        static_types.append(typ if not typ.is_dynamic_size else Uint256Definition())

    requires_dynamic_offset = any(typ.is_dynamic_size for typ in arg_types)

    dynamic_offset_counter = None
    if requires_dynamic_offset:
        # TODO refactor out old type objects
        dynamic_offset_counter = context.new_internal_variable(BaseType(32))
        dynamic_placeholder = context.new_internal_variable(BaseType(32))

    static_vars = [context.new_internal_variable(i) for i in static_types]

    # Populate static placeholders.
    for i, (node, typ) in enumerate(zip(arg_nodes, arg_types)):
        placeholder = static_vars[i]
        if not isinstance(typ, ArrayValueAbstractType):
            holder, maxlen = pack_args_by_32(
                holder, maxlen, prealloacted.get(i, node), typ, context, placeholder, pos=pos,
            )

    # Dynamic position starts right after the static args.
    if requires_dynamic_offset:
        holder.append(LLLnode.from_list(["mstore", dynamic_offset_counter, maxlen]))

    # Calculate maximum dynamic offset placeholders, used for gas estimation.
    for typ in arg_types:
        if typ.is_dynamic_size:
            maxlen += typ.size_in_bytes

    if requires_dynamic_offset:
        datamem_start = dynamic_placeholder + 32
    else:
        datamem_start = static_vars[0]

    # Copy necessary data into allocated dynamic section.
    for i, (node, typ) in enumerate(zip(arg_nodes, arg_types)):
        if isinstance(typ, ArrayValueAbstractType):
            if isinstance(node, vy_ast.Call) and node.func.get("id") == "empty":
                # TODO add support for this
                raise StructureException(
                    "Cannot use `empty` on Bytes or String types within an event log", node
                )
            pack_args_by_32(
                holder=holder,
                maxlen=maxlen,
                arg=prealloacted.get(i, node),
                typ=typ,
                context=context,
                placeholder=static_vars[i],
                datamem_start=datamem_start,
                dynamic_offset_counter=dynamic_offset_counter,
                pos=pos,
            )

    return holder, maxlen, dynamic_offset_counter, datamem_start
