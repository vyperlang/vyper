import random

import pytest

import vyper


@pytest.fixture
def huge_bytestring():
    r = random.Random(b"vyper")

    return bytes([r.getrandbits(8) for _ in range(0x6001)])


def test_contract_size_exceeded(huge_bytestring):
    code = f"""
@external
def a() -> bool:
    q: Bytes[24577] = {huge_bytestring}
    return True
"""
    with pytest.warns(vyper.warnings.ContractSizeLimitWarning):
        vyper.compile_code(code, output_formats=["bytecode_runtime"])


# test that each compilation run gets a fresh analysis and storage allocator
def test_shared_modules_allocation(make_input_bundle):
    lib1 = """
x: uint256
    """
    main1 = """
import lib1
initializes: lib1
    """
    main2 = """
import lib1
initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    vyper.compile_code(main1, input_bundle=input_bundle)
    vyper.compile_code(main2, input_bundle=input_bundle)

def test_precompile_call_success_flag():
    # Example Vyper contract code with precompile calls
    vyper_code = '''
@external
def test_ecrecover():
    success: bool = ecrecover(0x0, 0, 0x0, 0x0)
    assert success

@external
def test_identity():
    success: bool = identity(0x0)
    assert success
'''

    # Compile the Vyper contract
    compiled_contract = compile_contract(vyper_code)

    # Execute the contract and check the success flag
    result_ecrecover = execute_contract(compiled_contract, 'test_ecrecover')
    assert result_ecrecover.success, "ecrecover precompile call failed"

    result_identity = execute_contract(compiled_contract, 'test_identity')
    assert result_identity.success, "identity precompile call failed"

    # Test failure scenarios
    vyper_code_fail = '''
@external
def test_ecrecover_fail():
    success: bool = ecrecover(0x0, 0, 0x0, 0x0)
    assert not success

@external
def test_identity_fail():
    success: bool = identity(0x0)
    assert not success
'''

    compiled_contract_fail = compile_contract(vyper_code_fail)

    result_ecrecover_fail = execute_contract(compiled_contract_fail, 'test_ecrecover_fail')
    assert not result_ecrecover_fail.success, "ecrecover precompile call did not fail as expected"

    result_identity_fail = execute_contract(compiled_contract_fail, 'test_identity_fail')
    assert not result_identity_fail.success, "identity precompile call did not fail as expected"

pytest.main()