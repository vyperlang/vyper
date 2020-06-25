from vyper.parser import parser_utils
from vyper.parser.parser import parse_to_lll


def test_gas_call(get_contract_with_gas_estimation):
    gas_call = """
@public
def foo() -> uint256:
    return msg.gas
    """

    c = get_contract_with_gas_estimation(gas_call)

    assert c.foo(call={"gas": 50000}) < 50000
    assert c.foo(call={"gas": 50000}) > 25000

    print("Passed gas test")


def test_gas_estimate_repr():
    code = """
x: int128

@public
def __init__():
    self.x = 1
    """
    parser_utils.LLLnode.repr_show_gas = True
    out = parse_to_lll(code)
    assert "35261" in str(out)[:28]
    parser_utils.LLLnode.repr_show_gas = False
