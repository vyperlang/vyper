import pytest

from vyper import compile_code
from vyper.exceptions import TypeMismatch


@pytest.mark.parametrize("n", range(1, 32))
def test_literal_bytestrings_to_bytes_m(get_contract, n):
    test_data = "1" * n
    out = test_data.encode()

    bytes_m_typ = f"bytes{n}"
    contract_1 = f"""
@external
def foo() -> {bytes_m_typ}:
    return convert(b"{test_data}", {bytes_m_typ})

@external
def bar() -> {bytes_m_typ}:
    return convert("{test_data}", {bytes_m_typ})
    """

    contract_2 = f"""
@external
def fubar(x: String[{n}]) -> {bytes_m_typ}:
    return convert(x, {bytes_m_typ})
    """

    c1 = get_contract(contract_1)
    assert c1.foo() == out
    assert c1.bar() == out

    with pytest.raises(TypeMismatch):
        compile_code(contract_2)


def test_const(get_contract):
    code = """
a: public(constant(bytes5)) = convert(b"vyper", bytes5)
    """

    c = get_contract(code)
    assert c.a() == b"vyper"
