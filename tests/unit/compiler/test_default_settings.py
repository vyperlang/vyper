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
