from vyper.exceptions import TypeMismatch
from vyper.old_codegen.abi import abi_encode, abi_type_of, lll_tuple_from_args
from vyper.old_codegen.keccak256_helper import keccak256_helper
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import unwrap_location
from vyper.old_codegen.types.types import (
    BaseType,
    ByteArrayLike,
    ByteArrayType,
)


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


# docs.soliditylang.org/en/v0.8.6/abi-spec.html#events
def lll_node_for_log(expr, event, topic_nodes, data_nodes, pos, context):
    topics = _encode_log_topics(expr, event.event_id, topic_nodes, context)

    data = lll_tuple_from_args(data_nodes)

    # make a buffer for the encoded data output
    buf_maxlen = abi_type_of(data.typ).size_bound()
    buf = context.new_internal_variable(ByteArrayType(maxlen=buf_maxlen))

    # encode_data is an LLLnode which, cleverly, both encodes the data
    # and returns the length of the encoded data as a stack item.
    encode_data = abi_encode(buf, data, pos=pos, returns_len=True)

    assert len(topics) <= 4, "too many topics"  # sanity check
    log_opcode = "log" + str(len(topics))

    return LLLnode.from_list(
        [log_opcode, buf, encode_data] + topics,
        add_gas_estimate=_gas_bound(len(topics), buf_maxlen),
        typ=None,
        pos=pos,
        annotation=f"LOG event {event.signature}",
    )
