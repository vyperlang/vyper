def test_memory_deallocation(get_contract):
    code = """
event Shimmy:
    a: indexed(address)
    b: uint256

interface Other:
    def sendit(): nonpayable

@external
def foo(target: address) -> uint256[2]:
    log Shimmy(empty(address), 3)
    amount: uint256 = 1
    flargen: uint256 = 42
    extcall Other(target).sendit()
    return [amount, flargen]
    """

    code2 = """

@external
def sendit() -> bool:
    return True
    """

    c = get_contract(code)
    c2 = get_contract(code2)

    assert c.foo(c2.address) == [1, 42]
