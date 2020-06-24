def test_repeat(get_contract_from_lll, assert_compile_failed):
    good_lll = ["repeat", 0, 0, 1, ["seq"]]
    bad_lll_1 = ["repeat", 0, 0, 0, ["seq"]]
    bad_lll_2 = ["repeat", 0, 0, -1, ["seq"]]
    get_contract_from_lll(good_lll)
    assert_compile_failed(lambda: get_contract_from_lll(bad_lll_1), Exception)
    assert_compile_failed(lambda: get_contract_from_lll(bad_lll_2), Exception)
