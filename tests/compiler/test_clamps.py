def test_uclamplt(get_contract_from_ir, assert_compile_failed):
    ir = ["uclamplt", 2, 1]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["uclamplt", 1, 1]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["uclamplt", 0, 1]
    get_contract_from_ir(ir)


def test_uclample(get_contract_from_ir, assert_compile_failed):
    ir = ["uclample", 2, 1]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["uclample", 1, 1]
    get_contract_from_ir(ir)
    ir = ["uclample", 0, 1]
    get_contract_from_ir(ir)


def test_uclampgt(get_contract_from_ir, assert_compile_failed):
    ir = ["uclampgt", 1, 2]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["uclampgt", 1, 1]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["uclampgt", 1, 0]
    get_contract_from_ir(ir)


def test_uclampge(get_contract_from_ir, assert_compile_failed):
    ir = ["uclampge", 1, 2]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["uclampge", 1, 1]
    get_contract_from_ir(ir)
    ir = ["uclampge", 1, 0]
    get_contract_from_ir(ir)


def test_uclamplt_and_clamplt(get_contract_from_ir, assert_compile_failed):
    ir = ["uclamplt", 2, 1]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["uclamplt", 1, 1]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["uclamplt", 0, 1]
    get_contract_from_ir(ir)
    ir = ["clamplt", 2, 1]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["clamplt", 1, 1]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["clamplt", 0, 1]
    get_contract_from_ir(ir)


def test_uclample_clample(get_contract_from_ir, assert_compile_failed):
    ir = ["uclample", 2, 1]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["uclample", 1, 1]
    get_contract_from_ir(ir)
    ir = ["uclample", 0, 1]
    get_contract_from_ir(ir)
    ir = ["clample", 2, 1]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["clample", 1, 1]
    get_contract_from_ir(ir)
    ir = ["clample", 0, 1]
    get_contract_from_ir(ir)


def test_uclampgt_and_clampgt(get_contract_from_ir, assert_compile_failed):
    ir = ["uclampgt", 1, 2]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["uclampgt", 1, 1]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["uclampgt", 1, 0]
    get_contract_from_ir(ir)
    ir = ["clampgt", 1, 2]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["clampgt", 1, 1]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["clampgt", 1, 0]
    get_contract_from_ir(ir)


def test_uclampge_and_clampge(get_contract_from_ir, assert_compile_failed):
    ir = ["uclampge", 1, 2]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["uclampge", 1, 1]
    get_contract_from_ir(ir)
    ir = ["uclampge", 1, 0]
    get_contract_from_ir(ir)
    ir = ["clampge", 1, 2]
    assert_compile_failed(lambda: get_contract_from_ir(ir), Exception)
    ir = ["clampge", 1, 1]
    get_contract_from_ir(ir)
    ir = ["clampge", 1, 0]
    get_contract_from_ir(ir)
