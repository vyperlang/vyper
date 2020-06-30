def test_comment_test(get_contract_with_gas_estimation):
    comment_test = """
@external
def foo() -> int128:
    # Returns 3
    return 3
    """

    c = get_contract_with_gas_estimation(comment_test)
    assert c.foo() == 3
    print("Passed comment test")
