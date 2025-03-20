from pathlib import Path

import pytest

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
def test_check_passing(hevm_check_vyper, hevm, contract_path):
    check(contract_path, hevm, hevm_check_vyper)


@pytest.mark.hevm("--smttimeout", "10")
@pytest.mark.xfail(strict=True, reason="timeout or hevm can't handle the contract")
@pytest.mark.parametrize("contract_path", get_example_contracts())
def test_check_failing(hevm_check_vyper, hevm, contract_path):
    check(contract_path, hevm, hevm_check_vyper)


def check(contract_path, hevm, hevm_check_vyper):
    if not hevm:
        pytest.skip("Test requires hevm to be enabled")

    with open(contract_path, "r") as f:
        source_code = f.read()

    hevm_check_vyper(source_code)
