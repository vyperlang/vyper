# pragma version >=0.4.2
"""
@title XYZ Relayer
@author CurveFi
"""

version: public(constant(String[8])) = "1.0.0"


event SetMessenger:
    messenger: address


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

CODE_OFFSET: constant(uint256) = 3


OWNERSHIP_AGENT: public(immutable(address))
PARAMETER_AGENT: public(immutable(address))
EMERGENCY_AGENT: public(immutable(address))


agent: HashMap[Agent, address]
messenger: public(address)


@deploy
def __init__(_agent_blueprint: address, _messenger: address):
    self.messenger = _messenger
    log SetMessenger(messenger=_messenger)

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
    assert msg.sender == self.messenger

    extcall IAgent(self.agent[_agent]).execute(_messages)


@external
def set_messenger(_messenger: address):
    """
    @notice Set the messenger which verifies messages and is permitted to call `relay`.
    @dev Only callable by the OWNERSHIP_AGENT.
    """
    assert msg.sender == OWNERSHIP_AGENT

    self.messenger = _messenger
    log SetMessenger(messenger=_messenger)
