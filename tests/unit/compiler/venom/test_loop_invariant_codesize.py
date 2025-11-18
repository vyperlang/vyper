import pytest

from vyper import compile_code
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.venom.passes.loop_invariant_code_motion import LoopInvariantCodeMotionPass

LICM_REGRESSION_SOURCE = """
@external
def foo(x: uint256, y: uint256) -> uint256:
    total: uint256 = x
    for i: uint256 in range(5):
        if x * 2 + 1 > 5:
            total = total + y
    return total
"""


def _compile_contract():
    settings = Settings()
    settings.optimize = OptimizationLevel.CODESIZE
    settings.experimental_codegen = True
    output = compile_code(
        LICM_REGRESSION_SOURCE,
        output_formats=["bytecode"],
        settings=settings,
    )
    return output["bytecode"]


def test_loop_header_hoist_increases_codesize(monkeypatch):
    bytecode_with_licm = _compile_contract()

    monkeypatch.setattr(LoopInvariantCodeMotionPass, "run_pass", lambda self: None)
    bytecode_without_licm = _compile_contract()

    print("Bytecode with LICM:", len(bytecode_with_licm))
    print("Bytecode without LICM:", len(bytecode_without_licm))
    assert len(bytecode_with_licm) > len(bytecode_without_licm)
