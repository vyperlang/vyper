

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


def test_custom_units_struct(get_contract_with_gas_estimation):
    code = """
units: {
    cm: "centimer"
}

astruct: {
    value1: int128(cm)
}

@public
def test() -> int128(cm):
    self.astruct.value1 = 101
    return self.astruct.value1
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test() == 101
