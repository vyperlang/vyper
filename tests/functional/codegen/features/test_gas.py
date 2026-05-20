from vyper.compiler import compile_code
from vyper.compiler.settings import Settings


def test_gas_call(get_contract):
    gas_call = """
@external
def foo() -> uint256:
    return msg.gas
    """

    c = get_contract(gas_call)

    assert c.foo(gas=50000) < 50000
    assert c.foo(gas=50000) > 25000


def test_msg_gas_reads_are_not_removed():
    code = """
@external
def foo() -> uint256:
    g: uint256 = msg.gas
    return msg.gas
    """

    out = compile_code(
        code,
        output_formats=["opcodes_runtime"],
        settings=Settings(experimental_codegen=True),
    )

    assert out["opcodes_runtime"].split().count("GAS") == 2


def test_msg_gas_read_order_is_preserved():
    code = """
x: public(uint256)

@external
def foo() -> uint256:
    g: uint256 = msg.gas
    y: uint256 = self.x
    return unsafe_add(g, y)
    """

    out = compile_code(
        code,
        output_formats=["opcodes_runtime"],
        settings=Settings(experimental_codegen=True),
    )
    opcodes = out["opcodes_runtime"].split()

    assert opcodes.index("GAS") < opcodes.index("SLOAD")
