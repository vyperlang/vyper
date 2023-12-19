from vyper.codegen.abi_encoder import abi_encode
from vyper.codegen.core import get_type_for_exact_size, ir_tuple_from_args, unwrap_location
from vyper.codegen.ir_node import IRnode
from vyper.codegen.keccak256_helper import keccak256_helper
from vyper.exceptions import TypeMismatch
from vyper.semantics.types.bytestrings import _BytestringT


# docs.soliditylang.org/en/v0.8.6/abi-spec.html#indexed-event-encoding
def _encode_log_topics(expr, event_id, arg_nodes, context):
    topics = [event_id]

    for arg in arg_nodes:
        if arg.typ._is_prim_word:
            value = unwrap_location(arg)

        elif isinstance(arg.typ, _BytestringT):
            value = keccak256_helper(arg, context=context)
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


# docs.soliditylang.org/en/v0.8.6/abi-spec.html#events
def ir_node_for_log(expr, event, topic_nodes, data_nodes, context):
    """Taking IR nodes as arguments, create the IR node for a Log statement.

    Arguments:
      expr: The original Log expression
      buf: A pre-allocated buffer for the output
      _maxlen: The length of the buffer, for sanity checking
      event: The Event type
      topic_nodes: list of IRnodes which calculate the event topics
      data_nodes: list of IRnodes which calculate the event data
      context: current memory/frame context
    """
    topics = _encode_log_topics(expr, event.event_id, topic_nodes, context)

    data = ir_tuple_from_args(data_nodes)

    bufsz = data.typ.abi_type.size_bound()
    buf = context.new_internal_variable(get_type_for_exact_size(bufsz))

    # encode_data is an IRnode which, cleverly, both encodes the data
    # and returns the length of the encoded data as a stack item.
    encode_data = abi_encode(buf, data, context, returns_len=True, bufsz=bufsz)

    assert len(topics) <= 4, "too many topics"  # sanity check
    log_opcode = "log" + str(len(topics))

    return IRnode.from_list(
        [log_opcode, buf, encode_data] + topics,
        add_gas_estimate=_gas_bound(len(topics), bufsz),
        annotation=f"LOG event {event.signature}",
    )
