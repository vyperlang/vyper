import vyper


def test_basic_init_function(get_contract):
    code = """
val: public(uint256)

@deploy
def __init__(a: uint256):
    self.val = a
    """

    c = get_contract(code, *[123])

    assert c.val() == 123

    # Make sure the init code does not access calldata
    assembly = vyper.compile_code(code, output_formats=["asm"])["asm"].split(" ")
    ir_return_idx_start = assembly.index("{")
    ir_return_idx_end = assembly.index("}")

    assert "CALLDATALOAD" in assembly
    assert "CALLDATACOPY" not in assembly[:ir_return_idx_start] + assembly[ir_return_idx_end:]
    assert "CALLDATALOAD" not in assembly[:ir_return_idx_start] + assembly[ir_return_idx_end:]


def test_init_calls_internal(get_contract, assert_compile_failed, tx_failed):
    code = """
foo: public(uint8)

@internal
def bar(x: uint256) -> uint8:
    return convert(x, uint8) * 7

@deploy
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
    with tx_failed():
        c.baz()

    n = 255
    assert_compile_failed(lambda: get_contract(code, n))

    n = 256
    assert_compile_failed(lambda: get_contract(code, n))


# GH issue 3206
def test_nested_internal_call_from_ctor(get_contract):
    code = """
x: uint256

@deploy
def __init__():
    self.a()

@internal
def a():
    self.x += 1
    self.b()

@internal
def b():
    self.x += 2

@external
def test() -> uint256:
    return self.x
    """
    c = get_contract(code)
    assert c.test() == 3
