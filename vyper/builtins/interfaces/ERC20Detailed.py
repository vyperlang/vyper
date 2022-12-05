"""
NOTE: interface uses `String[1]` where 1 is the lower bound of the string returned by the function.
    For end-users this means they can't use `implements: ERC20Detailed` unless their implementation
    uses a value n >= 1. Regardless this is fine as one can't do String[0] where n == 0.
"""

interface_code = """
@view
@external
def name() -> String[1]:
    pass

@view
@external
def symbol() -> String[1]:
    pass

@view
@external
def decimals() -> uint8:
    pass
"""
