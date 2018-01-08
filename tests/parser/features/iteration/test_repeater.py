def test_basic_repeater(get_contract_with_gas_estimation):
    basic_repeater = """
@public
def repeat(z: num) -> num:
    x: num = 0
    for i in range(6):
        x = x + z
    return(x)
    """
    c = get_contract_with_gas_estimation(basic_repeater)
    assert c.repeat(9) == 54
    print('Passed basic repeater test')


def test_digit_reverser(get_contract_with_gas_estimation):
    digit_reverser = """
@public
def reverse_digits(x: num) -> num:
    dig: num[6]
    z: num = x
    for i in range(6):
        dig[i] = z % 10
        z = z / 10
    o: num = 0
    for i in range(6):
        o = o * 10 + dig[i]
    return o

    """

    c = get_contract_with_gas_estimation(digit_reverser)
    assert c.reverse_digits(123456) == 654321
    print('Passed digit reverser test')


def test_more_complex_repeater(get_contract_with_gas_estimation):
    more_complex_repeater = """
@public
def repeat() -> num:
    out: num = 0
    for i in range(6):
        out = out * 10
        for j in range(4):
            out = out + j
    return(out)
    """
    c = get_contract_with_gas_estimation(more_complex_repeater)
    assert c.repeat() == 666666
    print('Passed complex repeater test')


def test_offset_repeater(get_contract_with_gas_estimation):
    offset_repeater = """
@public
def sum() -> num:
    out: num = 0
    for i in range(80, 121):
        out = out + i
    return(out)
    """

    c = get_contract_with_gas_estimation(offset_repeater)
    assert c.sum() == 4100

    print('Passed repeater with offset test')


def test_offset_repeater_2(get_contract_with_gas_estimation):
    offset_repeater_2 = """
@public
def sum(frm: num, to: num) -> num:
    out: num = 0
    for i in range(frm, frm + 101):
        if i == to:
            break
        out = out + i
    return(out)
    """

    c = get_contract_with_gas_estimation(offset_repeater_2)
    assert c.sum(100, 99999) == 15150
    assert c.sum(70, 131) == 6100

    print('Passed more complex repeater with offset test')
