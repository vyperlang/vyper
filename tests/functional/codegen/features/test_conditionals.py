def test_conditional_return_code(get_contract_with_gas_estimation):
    conditional_return_code = """
@external
def foo(i: bool) -> int128:
    if i:
        return 5
    else:
        assert 2 != 0
        return 7
    """

    c = get_contract_with_gas_estimation(conditional_return_code)
    assert c.foo(True) == 5
    assert c.foo(False) == 7

    print("Passed conditional return tests")


def test_single_branch_underflow_public(get_contract_with_gas_estimation):
    code = """
@external
def doit():
    if False:
        raw_call(msg.sender, b"", max_outsize=0, value=0, gas=msg.gas)
    """
    c = get_contract_with_gas_estimation(code)
    c.doit()


def test_single_branch_underflow_private(get_contract_with_gas_estimation):
    code = """
@internal
def priv() -> uint256:
    return 1

@external
def dont_doit():
    if False:
        self.priv()
    """
    c = get_contract_with_gas_estimation(code)
    c.dont_doit()
