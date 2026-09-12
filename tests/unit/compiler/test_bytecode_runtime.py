import cbor2
import pytest

import vyper
from vyper.compiler.settings import OptimizationLevel, Settings

simple_contract_code = """
@external
def a() -> bool:
    return True
"""

many_functions = """
@external
def foo1():
    pass

@external
def foo2():
    pass

@external
def foo3():
    pass

@external
def foo4():
    pass

@external
def foo5():
    pass
"""

has_immutables = """
A_GOOD_PRIME: public(immutable(uint256))

@deploy
def __init__():
    self.A_GOOD_PRIME = 967
"""


def _parse_cbor_metadata(initcode):
    metadata_ofst = int.from_bytes(initcode[-2:], "big")
    metadata = cbor2.loads(initcode[-metadata_ofst:-2])
    return metadata


def test_bytecode_runtime():
    out = vyper.compile_code(simple_contract_code, output_formats=["bytecode_runtime", "bytecode"])

    assert len(out["bytecode"]) > len(out["bytecode_runtime"])
    assert out["bytecode_runtime"].removeprefix("0x") in out["bytecode"].removeprefix("0x")


def test_bytecode_signature(optimize, debug):
    out = vyper.compile_code(
        simple_contract_code, output_formats=["bytecode_runtime", "bytecode", "integrity"]
    )

    runtime_code = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    metadata = _parse_cbor_metadata(initcode)
    integrity_hash, runtime_len, data_section_lengths, immutables_len, compiler = metadata

    if debug and optimize == OptimizationLevel.CODESIZE:
        # debug forces dense jumptable no matter the size of selector table
        expected_data_section_lengths = [5, 7]
    else:
        expected_data_section_lengths = []

    assert integrity_hash.hex() == out["integrity"]

    assert runtime_len == len(runtime_code)
    assert data_section_lengths == expected_data_section_lengths
    assert immutables_len == 0
    assert compiler == {"vyper": list(vyper.version.version_tuple)}


def test_bytecode_signature_dense_jumptable():
    settings = Settings(optimize=OptimizationLevel.CODESIZE)

    out = vyper.compile_code(
        many_functions,
        output_formats=["bytecode_runtime", "bytecode", "integrity"],
        settings=settings,
    )

    runtime_code = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    metadata = _parse_cbor_metadata(initcode)
    integrity_hash, runtime_len, data_section_lengths, immutables_len, compiler = metadata

    assert integrity_hash.hex() == out["integrity"]

    assert runtime_len == len(runtime_code)
    assert data_section_lengths == [5, 35]
    assert immutables_len == 0
    assert compiler == {"vyper": list(vyper.version.version_tuple)}


def test_bytecode_signature_sparse_jumptable():
    settings = Settings(optimize=OptimizationLevel.GAS)

    out = vyper.compile_code(
        many_functions,
        output_formats=["bytecode_runtime", "bytecode", "integrity"],
        settings=settings,
    )

    runtime_code = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    metadata = _parse_cbor_metadata(initcode)
    integrity_hash, runtime_len, data_section_lengths, immutables_len, compiler = metadata

    assert integrity_hash.hex() == out["integrity"]

    assert runtime_len == len(runtime_code)
    assert data_section_lengths == [8]
    assert immutables_len == 0
    assert compiler == {"vyper": list(vyper.version.version_tuple)}


def test_bytecode_signature_immutables(debug, optimize):
    out = vyper.compile_code(
        has_immutables, output_formats=["bytecode_runtime", "bytecode", "integrity"]
    )

    runtime_code = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    metadata = _parse_cbor_metadata(initcode)
    integrity_hash, runtime_len, data_section_lengths, immutables_len, compiler = metadata

    if debug and optimize == OptimizationLevel.CODESIZE:
        # debug forces dense jumptable no matter the size of selector table
        expected_data_section_lengths = [5, 7]
    else:
        expected_data_section_lengths = []

    assert integrity_hash.hex() == out["integrity"]

    assert runtime_len == len(runtime_code)
    assert data_section_lengths == expected_data_section_lengths
    assert immutables_len == 32
    assert compiler == {"vyper": list(vyper.version.version_tuple)}


# check that deployed bytecode actually matches the cbor metadata
@pytest.mark.parametrize("code", [simple_contract_code, has_immutables, many_functions])
def test_bytecode_signature_deployed(code, get_contract, env):
    c = get_contract(code)
    deployed_code = env.get_code(c.address)

    metadata = _parse_cbor_metadata(c.bytecode)
    integrity_hash, runtime_len, data_section_lengths, immutables_len, compiler = metadata

    out = vyper.compile_code(code, output_formats=["integrity"])
    assert integrity_hash.hex() == out["integrity"]

    assert compiler == {"vyper": list(vyper.version.version_tuple)}

    # runtime_len includes data sections but not immutables
    assert len(deployed_code) == runtime_len + immutables_len


_ALPHABET = "abcdefghijklmnopqrstuvwxyz" * 4

# every literal is at least 96 bytes, so both optimization levels put it in
# a data section; the constructor and runtime literals differ so that they
# can be located in the initcode independently
GREETING = _ALPHABET[:100]
TAG = _ALPHABET[4:100]
FAREWELL = _ALPHABET.upper()[:96]

literals_contract_code = f"""
greeting: public(String[100])
TAG: public(immutable(String[96]))

@deploy
def __init__():
    self.greeting = "{GREETING}"
    TAG = "{TAG}"

@external
def farewell() -> String[96]:
    return "{FAREWELL}"
"""


@pytest.mark.parametrize("level", [OptimizationLevel.GAS, OptimizationLevel.CODESIZE])
def test_bytecode_literals_metadata(level):
    # constructor and runtime literals add data sections to the deploy and
    # the runtime code; the metadata must stay the initcode tail
    settings = Settings(experimental_codegen=True, optimize=level)
    out = vyper.compile_code(
        literals_contract_code, output_formats=["bytecode_runtime", "bytecode"], settings=settings
    )
    runtime_code = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    # the runtime literal is the runtime code's only data section (linear
    # selector dispatch has none); the constructor literals come before the
    # embedded runtime code, the metadata after it
    assert runtime_code in initcode
    assert FAREWELL.encode() in runtime_code
    assert initcode.index(GREETING.encode()) < initcode.index(runtime_code)
    assert initcode.index(TAG.encode()) < initcode.index(runtime_code)

    metadata = _parse_cbor_metadata(initcode)
    _, runtime_len, data_section_lengths, immutables_len, compiler = metadata
    assert runtime_len == len(runtime_code)
    assert data_section_lengths == [96]
    assert immutables_len == 32 + 96
    assert compiler == {"vyper": list(vyper.version.version_tuple)}
