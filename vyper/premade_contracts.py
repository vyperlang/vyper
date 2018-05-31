import ast

erc20 = """
class ERC20():
    def name() -> bytes32: constant
    def symbol() -> bytes32: constant
    def decimals() -> uint256: constant
    def balanceOf(_owner: address) -> uint256: constant
    def totalSupply() -> uint256: constant
    def transfer(_to: address, _amount: uint256) -> bool: modifying
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: modifying
    def approve(_spender: address, _amount: uint256) -> bool: modifying
    def allowance(_owner: address, _spender: address) -> uint256: modifying
"""


def prepare_code(code):
    return ast.parse(code).body[0]


premade_contracts = {
    "ERC20": prepare_code(erc20)
}
