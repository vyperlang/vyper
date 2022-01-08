from typing import Tuple

from vyper.abi_types import ABI_Tuple
from vyper.codegen.abi_encoder import abi_encode
from vyper.codegen.context import Context
from vyper.codegen.core import getpos, lll_tuple_from_args, unwrap_location
from vyper.codegen.keccak256_helper import keccak256_helper
from vyper.codegen.lll_node import LLLnode
from vyper.codegen.types.types import BaseType, ByteArrayLike, get_type_for_exact_size
from vyper.exceptions import TypeMismatch
from vyper.semantics.types import Event


# docs.soliditylang.org/en/v0.8.6/abi-spec.html#indexed-event-encoding
def _encode_log_topics(expr, event_id, arg_nodes, context):
    topics = [event_id]

    for arg in arg_nodes:
        if isinstance(arg.typ, BaseType):
            value = unwrap_location(arg)

        elif isinstance(arg.typ, ByteArrayLike):
            value = keccak256_helper(expr, arg, context=context)
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
    abi_t = ABI_Tuple([t.abi_type for t in arg_types])

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
    assert data.typ.abi_type.size_bound() == _maxlen, "bad buffer size"

    # encode_data is an LLLnode which, cleverly, both encodes the data
    # and returns the length of the encoded data as a stack item.
    encode_data = abi_encode(buf, data, context, pos=_pos, returns_len=True, bufsz=_maxlen)

    assert len(topics) <= 4, "too many topics"  # sanity check
    log_opcode = "log" + str(len(topics))

    return LLLnode.from_list(
        [log_opcode, buf, encode_data] + topics,
        add_gas_estimate=_gas_bound(len(topics), _maxlen),
        typ=None,
        pos=_pos,
        annotation=f"LOG event {event.signature}",
    )
