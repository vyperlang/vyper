import ast

erc20 = """
class ERC20():
    def name() -> bytes32: pass
    def symbol() -> bytes32: pass
    def decimals() -> uint256: pass
    def balanceOf(_owner: address) -> uint256: pass
    def totalSupply() -> uint256: pass
    def transfer(_to: address, _amount: uint256) -> bool: pass
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: pass
    def approve(_spender: address, _amount: uint256) -> bool: pass
    def allowance(_owner: address, _spender: address) -> uint256: pass
"""


def prepare_code(code):
    return ast.parse(code).body[0]


premade_contracts = {
    "ERC20": prepare_code(erc20)
}
