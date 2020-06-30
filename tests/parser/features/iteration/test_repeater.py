def test_basic_repeater(get_contract_with_gas_estimation):
    basic_repeater = """
@external
def repeat(z: int128) -> int128:
    x: int128 = 0
    for i in range(6):
        x = x + z
    return(x)
    """
    c = get_contract_with_gas_estimation(basic_repeater)
    assert c.repeat(9) == 54
    print("Passed basic repeater test")


def test_digit_reverser(get_contract_with_gas_estimation):
    digit_reverser = """
@external
def reverse_digits(x: int128) -> int128:
    dig: int128[6] = [0, 0, 0, 0, 0, 0]
    z: int128 = x
    for i in range(6):
        dig[i] = z % 10
        z = z / 10
    o: int128 = 0
    for i in range(6):
        o = o * 10 + dig[i]
    return o

    """

    c = get_contract_with_gas_estimation(digit_reverser)
    assert c.reverse_digits(123456) == 654321
    print("Passed digit reverser test")


def test_more_complex_repeater(get_contract_with_gas_estimation):
    more_complex_repeater = """
@external
def repeat() -> int128:
    out: int128 = 0
    for i in range(6):
        out = out * 10
        for j in range(4):
            out = out + j
    return(out)
    """

    c = get_contract_with_gas_estimation(more_complex_repeater)
    assert c.repeat() == 666666

    print("Passed complex repeater test")


def test_offset_repeater(get_contract_with_gas_estimation):
    offset_repeater = """
@external
def sum() -> int128:
    out: int128 = 0
    for i in range(80, 121):
        out = out + i
    return(out)
    """

    c = get_contract_with_gas_estimation(offset_repeater)
    assert c.sum() == 4100

    print("Passed repeater with offset test")


def test_offset_repeater_2(get_contract_with_gas_estimation):
    offset_repeater_2 = """
@external
def sum(frm: int128, to: int128) -> int128:
    out: int128 = 0
    for i in range(frm, frm + 101):
        if i == to:
            break
        out = out + i
    return(out)
    """

    c = get_contract_with_gas_estimation(offset_repeater_2)
    assert c.sum(100, 99999) == 15150
    assert c.sum(70, 131) == 6100

    print("Passed more complex repeater with offset test")


def test_loop_call_priv(get_contract_with_gas_estimation):
    code = """
@internal
def _bar() -> bool:
    return True

@external
def foo() -> bool:
    for i in range(3):
        self._bar()
    return True
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo() is True
