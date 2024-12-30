def test_repeat(get_contract_from_ir, assert_compile_failed):
    good_ir = ["repeat", 0, 0, 1, 1, ["seq"]]
    bad_ir_1 = ["repeat", 0, 0, 0, 0, ["seq"]]
    bad_ir_2 = ["repeat", 0, 0, -1, -1, ["seq"]]
    get_contract_from_ir(good_ir)
    assert_compile_failed(lambda: get_contract_from_ir(bad_ir_1), Exception)
    assert_compile_failed(lambda: get_contract_from_ir(bad_ir_2), Exception)
