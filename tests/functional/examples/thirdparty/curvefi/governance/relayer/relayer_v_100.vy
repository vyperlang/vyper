# pragma version >=0.4.2
"""
@title Relayer
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice Governance message relayer
"""

import tests.functional.examples.thirdparty.curvefi.governance.agent.agent_v_101 as agent_lib

event Relay:
    agent: agent_lib.Agent
    messages: DynArray[agent_lib.Message, agent_lib.MAX_MESSAGES]



MAX_BYTES: constant(uint256) = 1024
MAX_MESSAGES: constant(uint256) = 8

CODE_OFFSET: constant(uint256) = 3


OWNERSHIP_AGENT: public(immutable(address))
PARAMETER_AGENT: public(immutable(address))
EMERGENCY_AGENT: public(immutable(address))


agent: HashMap[agent_lib.Agent, agent_lib.IAgent]

BROADCASTER: public(immutable(address))


@deploy
def __init__(_broadcaster: address, _agent_blueprint: address):
    BROADCASTER = _broadcaster

    OWNERSHIP_AGENT = create_from_blueprint(_agent_blueprint, code_offset=CODE_OFFSET)
    PARAMETER_AGENT = create_from_blueprint(_agent_blueprint, code_offset=CODE_OFFSET)
    EMERGENCY_AGENT = create_from_blueprint(_agent_blueprint, code_offset=CODE_OFFSET)

    self.agent[agent_lib.Agent.OWNERSHIP] = agent_lib.IAgent(OWNERSHIP_AGENT)
    self.agent[agent_lib.Agent.PARAMETER] = agent_lib.IAgent(PARAMETER_AGENT)
    self.agent[agent_lib.Agent.EMERGENCY] = agent_lib.IAgent(EMERGENCY_AGENT)


@internal
def _relay(_agent: agent_lib.Agent, _messages: DynArray[agent_lib.Message, agent_lib.MAX_MESSAGES]):
    """
    @notice Receive messages for an agent and relay them.
    @param _agent The agent to relay messages to.
    @param _messages The sequence of messages to relay.
    """
    extcall self.agent[_agent].execute(_messages)

    log Relay(agent=_agent, messages=_messages)
