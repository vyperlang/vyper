from vyper.exceptions import TypeMismatch


def test_basic_in_list(get_contract_with_gas_estimation):
    code = """
@external
def testin(x: int128) -> bool:
    y: int128 = 1
    s: int128[4]  = [1, 2, 3, 4]
    if (x + 1) in s:
        return True
    return False
    """

    c = get_contract_with_gas_estimation(code)

    assert c.testin(0) is True
    assert c.testin(1) is True
    assert c.testin(2) is True
    assert c.testin(3) is True
    assert c.testin(4) is False
    assert c.testin(5) is False
    assert c.testin(-1) is False


def test_in_storage_list(get_contract_with_gas_estimation):
    code = """
allowed: int128[10]

@external
def in_test(x: int128) -> bool:
    self.allowed = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    if x in self.allowed:
        return True
    return False
    """

    c = get_contract_with_gas_estimation(code)

    assert c.in_test(1) is True
    assert c.in_test(9) is True
    assert c.in_test(11) is False
    assert c.in_test(-1) is False
    assert c.in_test(32000) is False


def test_in_calldata_list(get_contract_with_gas_estimation):
    code = """
@external
def in_test(x: int128, y: int128[10]) -> bool:
    if x in y:
        return True
    return False
    """

    c = get_contract_with_gas_estimation(code)

    assert c.in_test(1, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]) is True
    assert c.in_test(9, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]) is True
    assert c.in_test(11, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]) is False
    assert c.in_test(-1, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]) is False
    assert c.in_test(32000, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]) is False


def test_cmp_in_list(get_contract_with_gas_estimation):
    code = """
@external
def in_test(x: int128) -> bool:
    if x in [9, 7, 6, 5]:
        return True
    return False
    """

    c = get_contract_with_gas_estimation(code)

    assert c.in_test(1) is False
    assert c.in_test(-7) is False
    assert c.in_test(-9) is False
    assert c.in_test(5) is True
    assert c.in_test(7) is True


def test_cmp_not_in_list(get_contract_with_gas_estimation):
    code = """
@external
def in_test(x: int128) -> bool:
    if x not in [9, 7, 6, 5]:
        return True
    return False
    """

    c = get_contract_with_gas_estimation(code)

    assert c.in_test(1) is True
    assert c.in_test(-7) is True
    assert c.in_test(-9) is True
    assert c.in_test(5) is False
    assert c.in_test(7) is False


def test_mixed_in_list(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@external
def testin() -> bool:
    s: int128[4] = [1, 2, 3, 4]
    if "test" in s:
        return True
    return False
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), TypeMismatch)


def test_ownership(w3, tx_failed, get_contract_with_gas_estimation):
    code = """

owners: address[2]

@deploy
def __init__():
    self.owners[0] = msg.sender

@external
def set_owner(i: int128, new_owner: address):
    assert msg.sender in self.owners
    self.owners[i] = new_owner

@external
def is_owner() -> bool:
    return msg.sender in self.owners
    """
    a1 = w3.eth.accounts[1]
    c = get_contract_with_gas_estimation(code)

    assert c.is_owner() is True  # contract creator is owner.
    assert c.is_owner(call={"from": a1}) is False  # no one else is.

    # only an owner may set another owner.
    with tx_failed():
        c.set_owner(1, a1, call={"from": a1})

    c.set_owner(1, a1, transact={})
    assert c.is_owner(call={"from": a1}) is True

    # Owner in place 0 can be replaced.
    c.set_owner(0, a1, transact={})
    assert c.is_owner() is False


def test_in_fails_when_types_dont_match(get_contract_with_gas_estimation, tx_failed):
    code = """
@external
def testin(x: address) -> bool:
    s: int128[4] = [1, 2, 3, 4]
    if x in s:
        return True
    return False
"""
    with tx_failed(TypeMismatch):
        get_contract_with_gas_estimation(code)
