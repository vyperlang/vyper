import ast

erc20 = """
class ERC20():
    def symbol() -> bytes32: pass
    def balanceOf(_owner: address) -> num256: pass
    def totalSupply() -> num256: pass
    def transfer(_to: address, _amount: num256) -> bool: pass
    def transferFrom(_from: address, _to: address, _value: num(num256)) -> bool: pass
    def approve(_spender: address, _amount: num(num256)) -> bool: pass
    def allowance(_owner: address, _spender: address) -> num256: pass
"""


def prepare_code(code):
    return ast.parse(code).body[0]


premade_contracts = {
    "ERC20": prepare_code(erc20)
}
