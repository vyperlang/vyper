def test_calldatacopy(get_contract_from_ir):
    ir = ["calldatacopy", 32, 0, ["calldatasize"]]
    get_contract_from_ir(ir)
