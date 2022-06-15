def test_values_should_be_increasing_ints(get_contract):
    code = """
enum Action:
    BUY
    SELL
    CANCEL

@external
@view
def buy() -> Action:
    return Action.BUY

@external
@view
def sell() -> Action:
    return Action.SELL

@external
@view
def cancel() -> Action:
    return Action.CANCEL
    """
    c = get_contract(code)
    assert c.buy() == 1
    assert c.sell() == 2
    assert c.cancel() == 4
