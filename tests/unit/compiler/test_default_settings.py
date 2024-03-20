from vyper.codegen import core
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import OptimizationLevel, _is_debug_mode


def test_default_settings():
    source_code = ""
    compiler_data = CompilerData(source_code)
    _ = compiler_data.vyper_module  # force settings to be computed

    assert compiler_data.settings.optimize == OptimizationLevel.GAS


def test_default_opt_level():
    assert OptimizationLevel.default() == OptimizationLevel.GAS


def test_codegen_opt_level():
    assert core._opt_level == OptimizationLevel.GAS
    assert core._opt_gas() is True
    assert core._opt_none() is False
    assert core._opt_codesize() is False


def test_debug_mode(pytestconfig):
    debug_mode = pytestconfig.getoption("enable_compiler_debug_mode")
    assert _is_debug_mode() == debug_mode
