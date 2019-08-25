from vyper.exceptions import (
    InvalidLiteralException,
)


def test_function_with_units(get_contract_with_gas_estimation):
    code = """
units: {
    N: "Newton",
    m: "Meter",
    s: "Second",
}
@public
def foo(f: uint256(N), d: uint256(m), t: uint256(s)) -> uint256(N*m/s**2):
    return f * d / (t * t)

@public
def bar(a: uint256(m), b: uint256(m), c: uint256(m)) -> uint256(m**3):
    return (a * b * c)
    """

    c = get_contract_with_gas_estimation(code)

    assert c._classic_contract.abi[0]["outputs"] == [
        {"type": "uint256", "name": "out", "unit": "Newton-Meter per Second squared"}
    ]
    assert c._classic_contract.abi[0]["inputs"] == [
        {"type": "uint256", "name": "f", "unit": "Newton"},
        {"type": "uint256", "name": "d", "unit": "Meter"},
        {"type": "uint256", "name": "t", "unit": "Second"},
    ]
    assert c._classic_contract.abi[1]["outputs"] == [
        {"type": "uint256", "name": "out", "unit": "Meter**3"}
    ]
    assert c._classic_contract.abi[1]["inputs"] == [
        {"type": "uint256", "name": "a", "unit": "Meter"},
        {"type": "uint256", "name": "b", "unit": "Meter"},
        {"type": "uint256", "name": "c", "unit": "Meter"},
    ]


def test_event_with_units(get_contract_with_gas_estimation):
    code = """
units: {
    m: "Meter",
    s: "Second",
}
Speed: event({value: uint256(m/s)})
    """

    c = get_contract_with_gas_estimation(code)

    assert c._classic_contract.abi[0]["inputs"] == [
        {
            "type": "uint256",
            "name": "value",
            "indexed": False,
            "unit": "Meter per Second",
        }
    ]


def test_function_with_tuple_output(get_contract_with_gas_estimation):
    code = """
units: {
    m: "Meter",
    s: "Second",
}
@public
def foo(t: uint256(s), d: uint256(m)) -> (uint256(m), uint256(s)):
    return (d, t)
    """

    c = get_contract_with_gas_estimation(code)

    assert c._classic_contract.abi[0]["outputs"] == [
        {"type": "uint256", "name": "out", "unit": "Meter"},
        {"type": "uint256", "name": "out", "unit": "Second"},
    ]

    assert c._classic_contract.abi[0]["inputs"] == [
        {"type": "uint256", "name": "t", "unit": "Second"},
        {"type": "uint256", "name": "d", "unit": "Meter"},
    ]


def test_function_without_units(get_contract_with_gas_estimation):
    code = """
@public
def foo(a: uint256, b: uint256, c: uint256) -> uint256:
    return (a * b / c)
    """

    c = get_contract_with_gas_estimation(code)

    assert c._classic_contract.abi[0]["outputs"] == [{"type": "uint256", "name": "out"}]
    assert c._classic_contract.abi[0]["inputs"] == [
        {"type": "uint256", "name": "a"},
        {"type": "uint256", "name": "b"},
        {"type": "uint256", "name": "c"},
    ]


def test_function_call_explicit_unit_literal(get_contract, assert_compile_failed):
    code = """
@private
def unit_func(a: uint256(wei)) -> uint256(wei):
    return a + 1

@public
def foo() -> uint256(wei):
    c: uint256(wei) = self.unit_func(111)
    return c
    """

    assert_compile_failed(lambda: get_contract(code), InvalidLiteralException)
