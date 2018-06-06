

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


def test_custom_units_public(get_contract_with_gas_estimation):
    code = """
units: {
    mm: "millimeter"
}

a: int128(mm)
b: public(int128(mm))


@public
def test() -> int128(mm):
    self.a = 111
    return self.a
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test() == 111


def test_custom_units_events_and_func(get_contract_with_gas_estimation):
    code = """
units: {
    stock: "how much stock there is",
    token: "amount of token"
}


Transfer: event({_from: indexed(address), _to: indexed(address), _value: uint256(stock)})

@public
def initiate(token_addr: address, token_quantity: uint256(token)):
    pass
    """

    assert get_contract_with_gas_estimation(code)


def test_custom_units_after_convert(get_contract_with_gas_estimation):
    code = """
units: {
    cm: "centimeter",
}

@public
def test() -> uint256(cm):
    a: int128(cm) = 10
    b: uint256(cm) = convert(a, "uint256")
    return b
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test() == 10
