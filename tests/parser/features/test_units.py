from decimal import Decimal

from vyper.exceptions import TypeMismatchException, EventDeclarationException


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

    assert c._classic_contract.abi == [{
        "name": "foo",
        "outputs": [{
            "type": "uint256",
            "name": "out",
            "unit": "Newton-Meter per Second squared"
        }],
        "inputs": [{
            "type": "uint256",
            "name": "f",
            "unit": "Newton"
        }, {
            "type": "uint256",
            "name": "d",
            "unit": "Meter"
        }, {
            "type": "uint256",
            "name": "t",
            "unit": "Second"
        }],
        "constant": False,
        "payable": False,
        "type": "function",
        "gas": 1069
    }, {
        "name": "bar",
        "outputs": [{
            "type": "uint256",
            "name": "out",
            "unit": "Meter**3"
        }],
        "inputs": [{
            "type": "uint256",
            "name": "a",
            "unit": "Meter"
        }, {
            "type": "uint256",
            "name": "b",
            "unit": "Meter"
        }, {
            "type": "uint256",
            "name": "c",
            "unit": "Meter"
        }],
        "constant": False,
        "payable": False,
        "type": "function",
        "gas": 1381
    }]


def test_event_with_units(get_contract_with_gas_estimation):
    code = """
units: {
    m: "Meter",
    s: "Second",
}
Speed: event({value: uint256(m/s)})
    """

    c = get_contract_with_gas_estimation(code)

    assert c._classic_contract.abi == [{
        "name": "Speed",
        "inputs": [{
            "type": "uint256",
            "name": "value",
            "indexed": False,
            "unit": "Meter per Second"
        }],
        "anonymous": False,
        "type": "event"
    }]


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

    assert c._classic_contract.abi == [{
        "name": "foo",
        "outputs": [{
            "type": "uint256",
            "name": "out",
            "unit": "Meter"
        }, {
            "type": "uint256",
            "name": "out",
            "unit": "Second"
        }],
        "inputs": [{
            "type": "uint256",
            "name": "t",
            "unit": "Second"
        }, {
            "type": "uint256",
            "name": "d",
            "unit": "Meter"
        }],
        "constant": False,
        "payable": False,
        "type": "function",
        "gas": 391
    }]


def test_function_without_units(get_contract_with_gas_estimation):
    code = """
@public
def foo(a: uint256, b: uint256, c: uint256) -> uint256:
    return (a * b / c)
    """

    c = get_contract_with_gas_estimation(code)

    assert c._classic_contract.abi == [{
        "name": "foo",
        "outputs": [{
            "type": "uint256",
            "name": "out"
        }],
        "inputs": [{
            "type": "uint256",
            "name": "a"
        }, {
            "type": "uint256",
            "name": "b"
        }, {
            "type": "uint256",
            "name": "c"
        }],
        "constant": False,
        "payable": False,
        "type": "function",
        "gas": 655
    }]
