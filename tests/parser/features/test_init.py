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


def test_init_calls_internal(get_contract, assert_compile_failed, assert_tx_failed):
    code = """
foo: public(uint8)
@internal
def bar(x: uint256) -> uint8:
    return convert(x, uint8) * 7
@external
def __init__(a: uint256):
    self.foo = self.bar(a)

@external
def baz() -> uint8:
    return self.bar(convert(self.foo, uint256))
    """
    n = 5
    c = get_contract(code, n)
    assert c.foo() == n * 7
    assert c.baz() == 245  # 5*7*7

    n = 6
    c = get_contract(code, n)
    assert c.foo() == n * 7
    assert_tx_failed(lambda: c.baz())

    n = 255
    assert_compile_failed(lambda: get_contract(code, n))

    n = 256
    assert_compile_failed(lambda: get_contract(code, n))
