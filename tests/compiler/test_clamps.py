def test_uclamplt(get_contract_from_lll, assert_compile_failed):
    lll = ["uclamplt", 2, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["uclamplt", 1, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["uclamplt", 0, 1]
    get_contract_from_lll(lll)


def test_uclample(get_contract_from_lll, assert_compile_failed):
    lll = ["uclample", 2, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["uclample", 1, 1]
    get_contract_from_lll(lll)
    lll = ["uclample", 0, 1]
    get_contract_from_lll(lll)


def test_uclampgt(get_contract_from_lll, assert_compile_failed):
    lll = ["uclampgt", 1, 2]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["uclampgt", 1, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["uclampgt", 1, 0]
    get_contract_from_lll(lll)


def test_uclampge(get_contract_from_lll, assert_compile_failed):
    lll = ["uclampge", 1, 2]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["uclampge", 1, 1]
    get_contract_from_lll(lll)
    lll = ["uclampge", 1, 0]
    get_contract_from_lll(lll)


def test_uclamplt_and_clamplt(get_contract_from_lll, assert_compile_failed):
    lll = ["uclamplt", 2, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["uclamplt", 1, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["uclamplt", 0, 1]
    get_contract_from_lll(lll)
    lll = ["clamplt", 2, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["clamplt", 1, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["clamplt", 0, 1]
    get_contract_from_lll(lll)


def test_uclample_clample(get_contract_from_lll, assert_compile_failed):
    lll = ["uclample", 2, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["uclample", 1, 1]
    get_contract_from_lll(lll)
    lll = ["uclample", 0, 1]
    get_contract_from_lll(lll)
    lll = ["clample", 2, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["clample", 1, 1]
    get_contract_from_lll(lll)
    lll = ["clample", 0, 1]
    get_contract_from_lll(lll)


def test_uclampgt_and_clampgt(get_contract_from_lll, assert_compile_failed):
    lll = ["uclampgt", 1, 2]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["uclampgt", 1, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["uclampgt", 1, 0]
    get_contract_from_lll(lll)
    lll = ["clampgt", 1, 2]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["clampgt", 1, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["clampgt", 1, 0]
    get_contract_from_lll(lll)


def test_uclampge_and_clampge(get_contract_from_lll, assert_compile_failed):
    lll = ["uclampge", 1, 2]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["uclampge", 1, 1]
    get_contract_from_lll(lll)
    lll = ["uclampge", 1, 0]
    get_contract_from_lll(lll)
    lll = ["clampge", 1, 2]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ["clampge", 1, 1]
    get_contract_from_lll(lll)
    lll = ["clampge", 1, 0]
    get_contract_from_lll(lll)
