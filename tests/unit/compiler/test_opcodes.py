import re

import pytest

import vyper
from vyper.compiler.output import _build_opcodes
from vyper.compiler.settings import Settings
from vyper.evm import opcodes
from vyper.exceptions import CompilerPanic


def test_opcodes():
    code = """
@external
def a() -> bool:
    return True
    """

    out = vyper.compile_code(code, output_formats=["opcodes_runtime", "opcodes"])

    assert len(out["opcodes"]) > len(out["opcodes_runtime"])
    assert out["opcodes_runtime"] in out["opcodes"]


def test_version_check_no_begin_or_end():
    with pytest.raises(CompilerPanic):
        opcodes.version_check()


def test_version_check(evm_version):
    assert opcodes.version_check(begin=evm_version)
    assert opcodes.version_check(end=evm_version)
    assert opcodes.version_check(begin=evm_version, end=evm_version)
    if evm_version not in ("london",):
        assert not opcodes.version_check(end="london")
    london_check = opcodes.version_check(begin="london")
    assert london_check == (opcodes.EVM_VERSIONS[evm_version] >= opcodes.EVM_VERSIONS["london"])


def test_get_opcodes(evm_version):
    ops = opcodes.get_opcodes()
    version = opcodes.EVM_VERSIONS[evm_version]

    assert "CHAINID" in ops
    assert ops["CREATE2"][-1] == 32000

    assert ops["SLOAD"][-1] == 2100

    shanghai_plus = version >= opcodes.EVM_VERSIONS["shanghai"]
    assert ("PUSH0" in ops) == shanghai_plus

    cancun_plus = version >= opcodes.EVM_VERSIONS["cancun"]
    for op in ("TLOAD", "TSTORE", "MCOPY", "BLOBHASH", "BLOBBASEFEE"):
        assert (op in ops) == cancun_plus


def test_opcode_rulesets_are_monotonic():
    # opcodes are only ever added by newer forks. the override mechanism
    # cannot express removing one (see OPCODE_OVERRIDES), so if this ever
    # needs to change, the mechanism needs to change with it.
    for rulesets in (opcodes._evm_opcodes, opcodes._ir_opcodes):
        by_fork = [rulesets[i] for i in sorted(opcodes.EVM_VERSIONS.values())]
        for older, newer in zip(by_fork, by_fork[1:]):
            assert older.keys() <= newer.keys()


@pytest.mark.parametrize("version", ["london", "paris"])
@pytest.mark.parametrize("venom", [False, True])
def test_no_push0_before_shanghai(version, venom):
    # PUSH0 is shanghai+. regression test for the venom revert postamble,
    # which used to be a module-level constant and so froze in whichever
    # evm version happened to be active at import time.
    code = """
@external
def foo(x: uint256) -> uint256:
    assert x > 0
    return x
    """
    settings = Settings(evm_version=version, experimental_codegen=venom)
    asm = vyper.compile_code(code, settings=settings, output_formats=["asm"])["asm"]
    assert re.search(r"\bPUSH0\b", asm) is None


def test_build_opcodes():
    assert _build_opcodes(bytes.fromhex("610250")) == "PUSH2 0x0250"
    assert _build_opcodes(bytes.fromhex("612500")) == "PUSH2 0x2500"
    assert _build_opcodes(bytes.fromhex("610100")) == "PUSH2 0x0100"
    assert _build_opcodes(bytes.fromhex("611000")) == "PUSH2 0x1000"
    assert _build_opcodes(bytes.fromhex("62010300")) == "PUSH3 0x010300"
    assert (
        _build_opcodes(
            bytes.fromhex("7f6100000000000000000000000000000000000000000000000000000000000000")
        )
        == "PUSH32 0x6100000000000000000000000000000000000000000000000000000000000000"
    )
