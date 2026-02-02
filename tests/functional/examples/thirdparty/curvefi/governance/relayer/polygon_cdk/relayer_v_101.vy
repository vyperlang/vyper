# pragma version >=0.4.2
"""
@title Polygon zkEVM Relayer
@author CurveFi
@license MIT
@custom:version 1.0.1
"""

version: public(constant(String[8])) = "1.0.1"


event Relay:
    agent: Agent
    messages: DynArray[Message, MAX_MESSAGES]

event SetMessenger:
    messenger: address

event SetOriginNetwork:
    origin_network: uint32


interface IAgent:
    def execute(_messages: DynArray[Message, MAX_MESSAGES]): nonpayable


flag Agent:
    OWNERSHIP
    PARAMETER
    EMERGENCY


struct Message:
    target: address
    data: Bytes[MAX_BYTES]


MAX_BYTES: constant(uint256) = 1024
MAX_MESSAGES: constant(uint256) = 8
MAX_MESSAGE_RECEIVED: constant(uint256) = 9400
CODE_OFFSET: constant(uint256) = 3


OWNERSHIP_AGENT: public(immutable(address))
PARAMETER_AGENT: public(immutable(address))
EMERGENCY_AGENT: public(immutable(address))


agent: HashMap[Agent, address]

BROADCASTER: public(immutable(address))
MESSENGER: public(immutable(address))
ORIGIN_NETWORK: public(immutable(uint32))


@deploy
def __init__(_broadcaster: address, _agent_blueprint: address, _messenger: address, _origin_network: uint32):
    BROADCASTER = _broadcaster
    MESSENGER = _messenger
    log SetMessenger(messenger=_messenger)
    ORIGIN_NETWORK = _origin_network

    OWNERSHIP_AGENT = create_from_blueprint(_agent_blueprint, code_offset=CODE_OFFSET)
    PARAMETER_AGENT = create_from_blueprint(_agent_blueprint, code_offset=CODE_OFFSET)
    EMERGENCY_AGENT = create_from_blueprint(_agent_blueprint, code_offset=CODE_OFFSET)

    self.agent[Agent.OWNERSHIP] = OWNERSHIP_AGENT
    self.agent[Agent.PARAMETER] = PARAMETER_AGENT
    self.agent[Agent.EMERGENCY] = EMERGENCY_AGENT


@external
def relay(_agent: Agent, _messages: DynArray[Message, MAX_MESSAGES]):
    """
    @notice Receive messages for an agent and relay them.
    @param _agent The agent to relay messages to.
    @param _messages The sequence of messages to relay.
    """
    assert msg.sender == self

    extcall IAgent(self.agent[_agent]).execute(_messages)

    log Relay(agent=_agent, messages=_messages)


@external
def onMessageReceived(_origin_address: address, _origin_network: uint32, _data: Bytes[MAX_MESSAGE_RECEIVED]):
    assert msg.sender == MESSENGER
    assert _origin_address == BROADCASTER
    assert _origin_network == ORIGIN_NETWORK

    raw_call(self, _data)  # .relay()
