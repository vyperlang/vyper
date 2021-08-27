from typing import Tuple

from vyper.exceptions import TypeMismatch
from vyper.old_codegen.abi import (
    ABI_Tuple,
    abi_encode,
    abi_type_of,
    abi_type_of2,
    lll_tuple_from_args,
)
from vyper.old_codegen.context import Context
from vyper.old_codegen.keccak256_helper import keccak256_helper
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import getpos, unwrap_location
from vyper.old_codegen.types.types import (
    BaseType,
    ByteArrayLike,
    get_type_for_exact_size,
)
from vyper.semantics.types import Event


# docs.soliditylang.org/en/v0.8.6/abi-spec.html#indexed-event-encoding
def _encode_log_topics(expr, event_id, arg_nodes, context):
    topics = [event_id]

    for arg in arg_nodes:
        if isinstance(arg.typ, BaseType):
            value = unwrap_location(arg)

        elif isinstance(arg.typ, ByteArrayLike):
            value = keccak256_helper(expr, [arg], kwargs=None, context=context)
        else:
            # TODO block at higher level
            raise TypeMismatch("Event indexes may only be value types", expr)

        topics.append(value)

    return topics


def _gas_bound(num_topics, data_maxlen):
    LOG_BASE_GAS = 375
    GAS_PER_TOPIC = 375
    GAS_PER_LOG_BYTE = 8
    return LOG_BASE_GAS + GAS_PER_TOPIC * num_topics + GAS_PER_LOG_BYTE * data_maxlen


def allocate_buffer_for_log(event: Event, context: Context) -> Tuple[int, int]:
    """Allocate a buffer to ABI-encode the non-indexed (data) arguments into

    This must be done BEFORE compiling the event arguments to LLL,
    registering the buffer with the `context` variable (otherwise any
    function calls inside the event literal will clobber the buffer).
    """
    arg_types = list(event.arguments.values())  # the types of the arguments
    # remove non-data args, as those don't go into the buffer
    arg_types = [arg_t for arg_t, is_index in zip(arg_types, event.indexed) if not is_index]

    # all args get encoded as one big tuple
    abi_t = ABI_Tuple([abi_type_of2(arg_t) for arg_t in arg_types])

    # make a buffer for the encoded data output
    buf_maxlen = abi_t.size_bound()
    t = get_type_for_exact_size(buf_maxlen)
    return context.new_internal_variable(t), buf_maxlen


# docs.soliditylang.org/en/v0.8.6/abi-spec.html#events
def lll_node_for_log(expr, buf, _maxlen, event, topic_nodes, data_nodes, context):
    """Taking LLL nodes as arguments, create the LLL node for a Log statement.

    Arguments:
      expr: The original Log expression
      buf: A pre-allocated buffer for the output
      _maxlen: The length of the buffer, for sanity checking
      event: The Event type
      topic_nodes: list of LLLnodes which calculate the event topics
      data_nodes: list of LLLnodes which calculate the event data
      context: current memory/frame context
    """
    _pos = getpos(expr)

    topics = _encode_log_topics(expr, event.event_id, topic_nodes, context)

    data = lll_tuple_from_args(data_nodes)

    # sanity check, abi size_bound is the same calculated both ways
    assert abi_type_of(data.typ).size_bound() == _maxlen, "bad buffer size"

    # encode_data is an LLLnode which, cleverly, both encodes the data
    # and returns the length of the encoded data as a stack item.
    encode_data = abi_encode(buf, data, pos=_pos, returns_len=True)

    assert len(topics) <= 4, "too many topics"  # sanity check
    log_opcode = "log" + str(len(topics))

    return LLLnode.from_list(
        [log_opcode, buf, encode_data] + topics,
        add_gas_estimate=_gas_bound(len(topics), _maxlen),
        typ=None,
        pos=_pos,
        annotation=f"LOG event {event.signature}",
    )
