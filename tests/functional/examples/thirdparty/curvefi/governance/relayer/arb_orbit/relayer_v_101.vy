# pragma version >=0.4.2
"""
@title Arbitrum Relayer
@author CurveFi
@license MIT
@custom:version 1.0.1
"""

version: public(constant(String[8])) = "1.0.1"


interface IAgent:
    def execute(_messages: DynArray[Message, MAX_MESSAGES]): nonpayable

interface IArbSys:
    def wasMyCallersAddressAliased() -> bool: view
    def myCallersAddressWithoutAliasing() -> address: view


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


BROADCASTER: public(immutable(address))
ARBSYS: public(immutable(address))

OWNERSHIP_AGENT: public(immutable(address))
PARAMETER_AGENT: public(immutable(address))
EMERGENCY_AGENT: public(immutable(address))


agent: HashMap[Agent, address]


@deploy
def __init__(broadcaster: address, _agent_blueprint: address, _arbsys: address):
    BROADCASTER = broadcaster
    ARBSYS = _arbsys

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
    assert staticcall IArbSys(ARBSYS).wasMyCallersAddressAliased()
    assert staticcall IArbSys(ARBSYS).myCallersAddressWithoutAliasing() == BROADCASTER

    extcall IAgent(self.agent[_agent]).execute(_messages)
