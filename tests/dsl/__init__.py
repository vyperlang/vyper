"""
DSL for building Vyper contracts in tests.

Example usage:
    from tests.dsl import CodeModel

    # create a model
    model = CodeModel()

    # define storage variables
    balance = model.storage_var('balance: uint256')
    owner = model.storage_var('owner: address')

    # build a simple contract
    code = (model
        .function('__init__()')
        .deploy()
        .body(f'{owner} = msg.sender')
        .done()
        .function('deposit()')
        .external()
        .payable()
        .body(f'{balance} += msg.value')
        .done()
        .function('get_balance() -> uint256')
        .external()
        .view()
        .body(f'return {balance}')
        .done()
        .build())

    # The generated code will be:
    # balance: uint256
    # owner: address
    #
    # @deploy
    # def __init__():
    #     self.owner = msg.sender
    #
    # @external
    # @payable
    # def deposit():
    #     self.balance += msg.value
    #
    # @external
    # @view
    # def get_balance() -> uint256:
    #     return self.balance
"""

from tests.dsl.code_model import CodeModel, VarRef

__all__ = [CodeModel, VarRef]
