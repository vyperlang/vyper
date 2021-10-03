def test_simple_usage(get_contract):
    code = """
VALUE: immutable(uint256)

@external
def __init__(_value: uint256):
    VALUE = _value

@view
@external
def get_value() -> uint256:
    return VALUE
"""
    c = get_contract(code, 42)
    assert c.get_value() == 42
