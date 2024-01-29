import pytest

import vyper
from vyper.compiler.output import _build_opcodes
from vyper.evm import opcodes
from vyper.exceptions import CompilerPanic


@pytest.fixture(params=list(opcodes.EVM_VERSIONS))
def evm_version(request):
    default = opcodes.active_evm_version
    try:
        opcodes.active_evm_version = opcodes.EVM_VERSIONS[request.param]
        yield request.param
    finally:
        opcodes.active_evm_version = default


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
    if evm_version not in ("istanbul"):
        assert not opcodes.version_check(end="istanbul")
    istanbul_check = opcodes.version_check(begin="istanbul")
    assert istanbul_check == (opcodes.EVM_VERSIONS[evm_version] >= opcodes.EVM_VERSIONS["istanbul"])


def test_get_opcodes(evm_version):
    ops = opcodes.get_opcodes()

    assert "CHAINID" in ops
    assert ops["CREATE2"][-1] == 32000

    if evm_version in ("london", "berlin", "paris", "shanghai", "cancun"):
        assert ops["SLOAD"][-1] == 2100
    else:
        assert evm_version == "istanbul"
        assert ops["SLOAD"][-1] == 800

    if evm_version in ("shanghai", "cancun"):
        assert "PUSH0" in ops

    if evm_version in ("cancun",):
        for op in ("TLOAD", "TSTORE", "MCOPY"):
            assert op in ops
    else:
        for op in ("TLOAD", "TSTORE", "MCOPY"):
            assert op not in ops


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
