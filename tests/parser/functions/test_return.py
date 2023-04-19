def test_correct_abi_right_padding(tester, w3, get_contract_with_gas_estimation):
    selfcall_code_6 = """
@external
def hardtest(arg1: Bytes[64], arg2: Bytes[64]) -> Bytes[128]:
    return concat(arg1, arg2)
    """

    c = get_contract_with_gas_estimation(selfcall_code_6)

    assert c.hardtest(b"hello" * 5, b"hello" * 10) == b"hello" * 15

    # Make sure underlying structe is correctly right padded
    classic_contract = c._classic_contract
    func = classic_contract.functions.hardtest(b"hello" * 5, b"hello" * 10)
    tx = func.build_transaction({"gasPrice": 0})
    del tx["chainId"]
    del tx["gasPrice"]

    tx["from"] = w3.eth.accounts[0]
    res = w3.to_bytes(hexstr=tester.call(tx))

    static_offset = int.from_bytes(res[:32], "big")
    assert static_offset == 32

    dyn_section = res[static_offset:]
    assert len(dyn_section) % 32 == 0  # first right pad assert

    len_value = int.from_bytes(dyn_section[:32], "big")

    assert len_value == len(b"hello" * 15)
    assert dyn_section[32 : 32 + len_value] == b"hello" * 15
    # second right pad assert
    assert dyn_section[32 + len_value :] == b"\x00" * (len(dyn_section) - 32 - len_value)
