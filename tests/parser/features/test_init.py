import vyper


def test_basic_init_function(get_contract):
    code = """
val: public(uint256)

@external
def __init__(a: uint256):
    self.val = a
    """

    c = get_contract(code, *[123])

    assert c.val() == 123

    # Make sure the init code does not access calldata
    opcodes = vyper.compile_code(code, ["opcodes"])["opcodes"].split(" ")
    ir_return_idx = opcodes.index("JUMP")

    assert "CALLDATALOAD" in opcodes
    assert "CALLDATACOPY" not in opcodes[:ir_return_idx]
    assert "CALLDATALOAD" not in opcodes[:ir_return_idx]
