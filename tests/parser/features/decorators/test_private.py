def test_private_test(get_contract_with_gas_estimation):
    private_test_code = """
@private
def a() -> num:
    return 5

@public
def returnten() -> num:
    return self.a() * 2
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.returnten() == 10

    print("Passed private function test")
