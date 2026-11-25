import pytest

from vyper.codegen import core
from vyper.compiler import compile_code
from vyper.compiler.output import build_asm_output, build_asm_runtime_output
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import OptimizationLevel, Settings, _is_debug_mode, get_global_settings
from vyper.exceptions import EvmVersionException


def test_default_settings():
    source_code = ""
    compiler_data = CompilerData(source_code)
    _ = compiler_data.vyper_module  # force settings to be computed

    assert compiler_data.settings.optimize == OptimizationLevel.GAS


def test_default_opt_level():
    assert OptimizationLevel.default() == OptimizationLevel.GAS


def test_codegen_opt_level(optimize):
    gas_levels = (OptimizationLevel.GAS, OptimizationLevel.O2, OptimizationLevel.O3)
    lowering_only_levels = (OptimizationLevel.NONE, OptimizationLevel.O1)
    codesize_levels = (OptimizationLevel.CODESIZE, OptimizationLevel.Os)

    assert core._opt_gas() == (optimize in gas_levels)
    assert core._opt_lowering_only_ir() == (optimize in lowering_only_levels)
    assert core._opt_codesize() == (optimize in codesize_levels)

    # the three must partition OptimizationLevel: codegen dispatches on them
    # exhaustively, so a new level cannot silently select the wrong shape.
    assert sum([core._opt_gas(), core._opt_lowering_only_ir(), core._opt_codesize()]) == 1


def test_debug_mode(pytestconfig):
    debug_mode = pytestconfig.getoption("enable_compiler_debug_mode")
    assert _is_debug_mode() == debug_mode


@pytest.mark.parametrize("target,ambient", [("paris", None), ("cancun", "paris")])
def test_venom_compiler_data_uses_own_settings(monkeypatch, target, ambient):
    ambient_settings = Settings(evm_version=ambient) if ambient else None
    monkeypatch.setattr("vyper.compiler.settings._settings", ambient_settings)

    source_code = """
value: public(uint256)

@external
@nonreentrant
def bump():
    self.value += 1
"""
    settings = Settings(experimental_codegen=True, evm_version=target)
    formats = ["layout", "asm_runtime", "bytecode_runtime", "asm", "bytecode"]
    expected = compile_code(source_code, output_formats=formats, settings=settings)
    compiler_data = CompilerData(source_code, settings=settings)

    # Request each phase directly so an outer bytecode calculation cannot mask a missing anchor.
    assert compiler_data.storage_layout == expected["layout"]
    assert build_asm_runtime_output(compiler_data) == expected["asm_runtime"]
    assert "0x" + compiler_data.bytecode_runtime.hex() == expected["bytecode_runtime"]
    assert build_asm_output(compiler_data) == expected["asm"]
    assert "0x" + compiler_data.bytecode.hex() == expected["bytecode"]
    assert get_global_settings() is ambient_settings


def test_compiler_data_analysis_uses_pragma_evm_version(monkeypatch):
    ambient_settings = Settings(evm_version="cancun")
    monkeypatch.setattr("vyper.compiler.settings._settings", ambient_settings)
    compiler_data = CompilerData("#pragma evm-version shanghai\nvalue: transient(uint256)")

    with pytest.raises(EvmVersionException, match="transient"):
        _ = compiler_data.annotated_vyper_module
    assert get_global_settings() is ambient_settings
