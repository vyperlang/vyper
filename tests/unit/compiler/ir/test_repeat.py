def test_repeat(get_contract_from_ir, assert_compile_failed):
    good_ir = ["repeat", "i", 0, 1, 1, ["seq"]]
    # bound 0: no iterations, gets a loop-free lowering
    good_ir_2 = ["repeat", "i", 0, 0, 0, ["seq"]]
    bad_ir_1 = ["repeat", 0, 0, 0, 0, ["seq"]]
    bad_ir_2 = ["repeat", 0, 0, -1, -1, ["seq"]]
    get_contract_from_ir(good_ir)
    get_contract_from_ir(good_ir_2)
    assert_compile_failed(lambda: get_contract_from_ir(bad_ir_1), Exception)
    assert_compile_failed(lambda: get_contract_from_ir(bad_ir_2), Exception)


def test_repeat_bound_zero_runtime_rounds(get_contract_from_ir):
    # bound-0 repeat with non-literal rounds emits the zero-rounds guard
    # even though rounds and rounds_bound are not structurally comparable
    ir = [
        "deploy",
        0,
        ["seq", ["repeat", "i", 0, ["calldataload", 4], 0, ["seq"]], ["return", 0, 0], "stop"],
        0,
    ]
    abi = [
        {
            "name": "test",
            "outputs": [],
            "inputs": [{"type": "uint256", "name": "n"}],
            "stateMutability": "nonpayable",
            "type": "function",
        }
    ]
    c = get_contract_from_ir(ir, abi=abi)
    c.test(0)
    # nonzero rounds terminates after `rounds` iterations (would run out
    # of gas if the loop wrapped around)
    c.test(1)
