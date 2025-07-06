# pragma version >=0.4.2
"""
@title CurveXGovTaikoRelayer
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@custom:version 0.0.1
@notice Taiko governance message relayer
"""

version: public(constant(String[8])) = "0.0.1"

import contracts.governance.relayer.relayer_v_100 as Relayer

initializes: Relayer


interface IBridge:
    def context() -> Context: view

struct Context:
    msgHash: bytes32  # Message hash.
    msgFrom: address  # Sender's address.
    srcChainId: uint64  # Source chain ID.


BRIDGE: public(immutable(IBridge))


@deploy
def __init__(_broadcaster: address, _agent_blueprint: address):
    # Retrieve Bridge address 0x{decimal CHAIN_ID}0...001
    mul10: uint256 = 1
    for i: uint256 in range(39):
        mul10 *= 10
        if mul10 > chain.id:
            break
    addr: uint256 = 1
    mul16: uint256 = pow_mod256(16, 40)
    for i: uint256 in range(39):
        mul10 //= 10
        mul16 //= 16
        if mul10 == 0:
            break
        addr += mul16 * ((chain.id // mul10) % 10)
    BRIDGE = IBridge(convert(addr, address))

    Relayer.__init__(_broadcaster, _agent_blueprint)


exports: Relayer.__interface__


@external
def onMessageInvocation(_data: Bytes[10000]):
    """
    @notice Call handler from Taiko bridge
    @param _data ABI encoded data of governance messages
    """
    assert msg.sender == BRIDGE.address
    context: Context = staticcall BRIDGE.context()
    assert context.msgFrom == Relayer.BROADCASTER
    assert context.srcChainId == 1

    agent: Relayer.agent_lib.Agent = empty(Relayer.agent_lib.Agent)
    messages: DynArray[Relayer.agent_lib.Message, Relayer.agent_lib.MAX_MESSAGES] = []
    agent, messages = abi_decode(
        _data,
        (Relayer.agent_lib.Agent, DynArray[Relayer.agent_lib.Message, Relayer.agent_lib.MAX_MESSAGES]),
    )
    Relayer._relay(agent, messages)
