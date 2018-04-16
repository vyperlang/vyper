

def test_custom_units(get_contract_with_gas_estimation):
    code = """
units: {
    cm: "centimeter",
    km: "kilometer"
}

# global storage
a: int128(cm)


@public
def test() -> int128(km):
    b: int128(km)
    b = 100
    return b
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test() == 100
