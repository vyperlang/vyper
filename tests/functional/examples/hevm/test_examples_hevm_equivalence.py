import copy
from pathlib import Path

import pytest

import tests.hevm
from vyper.compiler import compile_code
from vyper.compiler.settings import OptimizationLevel

# test the legacy/venom bytecode equivalence via HEVM
# the tests are divided to passing/failing
# HEVM currently lacks some features necessary for successful verification
# once those features are added, the failing tests will start passing
# and will fail the testsuite (see the strict=True marker)
# additionally, we provide 10s timeout so the failing tests don't deplete resources

PASSING = ["examples/storage/storage.vy", "examples/storage/advanced_storage.vy"]


def get_example_contracts(passing=False):
    root = Path(__file__).parent.parent.parent.parent.parent
    examples_dir = root / "examples"
    vy_file_paths = [str(p) for p in examples_dir.rglob("*.vy")]
    passing_contracts = [str(root / path) for path in PASSING]
    if passing:
        return passing_contracts
    failing_contracts = [path for path in vy_file_paths if path not in passing_contracts]
    return failing_contracts


@pytest.mark.hevm
@pytest.mark.parametrize("contract_path", get_example_contracts(passing=True))
def test_check_passing(hevm, contract_path, compiler_settings):
    check(contract_path, hevm, compiler_settings)


@pytest.mark.hevm
@pytest.mark.xfail(strict=True, reason="timeout or hevm can't handle the contract")
@pytest.mark.parametrize("contract_path", get_example_contracts(passing=False))
def test_check_failing(hevm, contract_path, compiler_settings):
    check(contract_path, hevm, compiler_settings, addl_args=["--smttimeout", "10"])


def check(contract_path, hevm, compiler_settings, addl_args: list = None):
    if not hevm:
        pytest.skip("Test requires hevm to be enabled")

    with open(contract_path, "r") as f:
        source_code = f.read()

    settings1 = copy.copy(compiler_settings)
    settings1.experimental_codegen = False
    settings1.optimize = OptimizationLevel.NONE
    settings2 = copy.copy(compiler_settings)
    settings2.experimental_codegen = True
    settings2.optimize = OptimizationLevel.NONE

    bytecode1 = compile_code(source_code, output_formats=("bytecode_runtime",), settings=settings1)[
        "bytecode_runtime"
    ]
    bytecode2 = compile_code(source_code, output_formats=("bytecode_runtime",), settings=settings2)[
        "bytecode_runtime"
    ]

    tests.hevm.hevm_check_bytecode(bytecode1, bytecode2, addl_args=addl_args)
