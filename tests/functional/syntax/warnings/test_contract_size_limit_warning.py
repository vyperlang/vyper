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
    with pytest.warns(vyper.warnings.ContractSizeLimit):
        vyper.compile_code(code, output_formats=["bytecode_runtime"])
