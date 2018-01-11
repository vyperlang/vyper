def test_continue1(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> bool:
    for i in range(2):
        continue
        return False
    return True
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo()


def test_continue2(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> num:
    x: num = 0
    for i in range(3):
        x += 1
        continue
        x -= 1
    return x
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 3


def test_continue3(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> num:
    x: num = 0
    for i in range(3):
        x += i
        continue
    return x
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 3


def test_continue4(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> num:
    x: num = 0
    for i in range(6):
        if i % 2 == 0:
            continue
        x += 1
    return x
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 3
