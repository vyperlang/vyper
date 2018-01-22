def test_break_test(get_contract_with_gas_estimation):
    break_test = """
@public
def log(n: num) -> num:
    c: decimal = n * 1.0
    output: num = 0
    for i in range(400):
        c = c / 1.2589
        if c < 1.0:
            output = i
            break
    return output
    """

    c = get_contract_with_gas_estimation(break_test)
    assert c.log(1) == 0
    assert c.log(2) == 3
    assert c.log(10) == 10
    assert c.log(200) == 23
    print('Passed for-loop break test')


def test_break_test_2(get_contract_with_gas_estimation):
    break_test_2 = """
@public
def log(n: num) -> num:
    c: decimal = n * 1.0
    output: num = 0
    for i in range(40):
        if c < 10:
            output = i * 10
            break
        c = c / 10
    for i in range(10):
        c = c / 1.2589
        if c < 1.0:
            output = output + i
            break
    return output
    """

    c = get_contract_with_gas_estimation(break_test_2)
    assert c.log(1) == 0
    assert c.log(2) == 3
    assert c.log(10) == 10
    assert c.log(200) == 23
    assert c.log(4000000) == 66
    print('Passed for-loop break test 2')


def test_break_test_3(get_contract_with_gas_estimation):
    break_test_3 = """
@public
def log(n: num) -> num:
    c: decimal = decimal(n)
    output: num = 0
    for i in range(40):
        if c < 10:
            output = i * 10
            break
        c /= 10
    for i in range(10):
        c /= 1.2589
        if c < 1:
            output = output + i
            break
    return output
    """
    c = get_contract_with_gas_estimation(break_test_3)
    assert c.log(1) == 0
    assert c.log(2) == 3
    assert c.log(10) == 10
    assert c.log(200) == 23
    assert c.log(4000000) == 66
    print('Passed aug-assignment break composite test')
