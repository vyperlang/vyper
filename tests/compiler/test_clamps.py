

def test_uclamplt(t, get_contract_from_lll, assert_compile_failed):
    lll = ['uclamplt', 2, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['uclamplt', 1, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['uclamplt', 0, 1]
    get_contract_from_lll(lll)


def test_uclample(t, get_contract_from_lll, assert_compile_failed):
    lll = ['uclample', 2, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['uclample', 1, 1]
    get_contract_from_lll(lll)
    lll = ['uclample', 0, 1]
    get_contract_from_lll(lll)


def test_uclampgt(t, get_contract_from_lll, assert_compile_failed):
    lll = ['uclampgt', 1, 2]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['uclampgt', 1, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['uclampgt', 1, 0]
    get_contract_from_lll(lll)


def test_uclampge(t, get_contract_from_lll, assert_compile_failed):
    lll = ['uclampge', 1, 2]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['uclampge', 1, 1]
    get_contract_from_lll(lll)
    lll = ['uclampge', 1, 0]
    get_contract_from_lll(lll)


def test_uclamplt_and_clamplt(t, get_contract_from_lll, assert_compile_failed):
    lll = ['uclamplt', 2, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['uclamplt', 1, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['uclamplt', 0, 1]
    get_contract_from_lll(lll)
    lll = ['clamplt', 2, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['clamplt', 1, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['clamplt', 0, 1]
    get_contract_from_lll(lll)


def test_uclample_clample(t, get_contract_from_lll, assert_compile_failed):
    lll = ['uclample', 2, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['uclample', 1, 1]
    get_contract_from_lll(lll)
    lll = ['uclample', 0, 1]
    get_contract_from_lll(lll)
    lll = ['clample', 2, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['clample', 1, 1]
    get_contract_from_lll(lll)
    lll = ['clample', 0, 1]
    get_contract_from_lll(lll)


def test_uclampgt_and_clampgt(t, get_contract_from_lll, assert_compile_failed):
    lll = ['uclampgt', 1, 2]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['uclampgt', 1, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['uclampgt', 1, 0]
    get_contract_from_lll(lll)
    lll = ['clampgt', 1, 2]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['clampgt', 1, 1]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['clampgt', 1, 0]
    get_contract_from_lll(lll)


def test_uclampge_and_clampge(t, get_contract_from_lll, assert_compile_failed):
    lll = ['uclampge', 1, 2]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['uclampge', 1, 1]
    get_contract_from_lll(lll)
    lll = ['uclampge', 1, 0]
    get_contract_from_lll(lll)
    lll = ['clampge', 1, 2]
    assert_compile_failed(lambda: get_contract_from_lll(lll), Exception)
    lll = ['clampge', 1, 1]
    get_contract_from_lll(lll)
    lll = ['clampge', 1, 0]
    get_contract_from_lll(lll)
