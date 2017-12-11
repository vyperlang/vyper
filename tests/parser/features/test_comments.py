def test_comment_test(get_contract_with_gas_estimation):
    comment_test = """
@public
def foo() -> num:
    # Returns 3
    return 3
    """

    c = get_contract_with_gas_estimation(comment_test)
    assert c.foo() == 3
    print('Passed comment test')
