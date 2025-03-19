from pathlib import Path

import pytest

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
def test_check_passing(check_hevm_eq, contract_path):
    check(contract_path, check_hevm_eq)


@pytest.mark.hevm("--smttimeout", "10")
@pytest.mark.xfail(reason="timeout or hevm can't handle the contract")
@pytest.mark.parametrize("contract_path", get_example_contracts())
def test_check_failing(check_hevm_eq, contract_path):
    check(contract_path, check_hevm_eq)


def check(contract_path, check_hevm_eq):
    with open(contract_path, "r") as f:
        source_code = f.read()

    check_hevm_eq(source_code)
