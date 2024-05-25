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
