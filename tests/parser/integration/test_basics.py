def test_null_code(get_contract_with_gas_estimation):
    null_code = """
@public
def foo():
    pass
    """
    c = get_contract_with_gas_estimation(null_code)
    c.foo()
    print('Successfully executed a null function')


def test_basic_code(get_contract_with_gas_estimation):
    basic_code = """
@public
def foo(x: num) -> num:
    return x * 2

    """
    c = get_contract_with_gas_estimation(basic_code)
    assert c.foo(9) == 18
    print('Passed basic code test')


def test_selfcall_code_3(get_contract_with_gas_estimation, utils):
    selfcall_code_3 = """
@public
def _hashy2(x: bytes <= 100) -> bytes32:
    return sha3(x)

@public
def return_hash_of_cow_x_30() -> bytes32:
    return self._hashy2("cowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcow")

@public
def _len(x: bytes <= 100) -> num:
    return len(x)

@public
def returnten() -> num:
    return self._len("badminton!")
    """

    c = get_contract_with_gas_estimation(selfcall_code_3)
    assert c.return_hash_of_cow_x_30() == utils.sha3(b'cow' * 30)
    assert c.returnten() == 10

    print("Passed single variable-size argument self-call test")
