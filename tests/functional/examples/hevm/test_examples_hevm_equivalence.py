from pathlib import Path

import pytest

PASSING = ["examples/storage/storage.vy", "examples/storage/advanced_storage.vy"]


def get_example_contracts():
    root = Path(__file__).parent.parent.parent.parent.parent
    examples_dir = root / "examples"
    contract_paths = [str(p) for p in examples_dir.rglob("*.vy")]
    return contract_paths


@pytest.mark.hevm("--smttimeout", "10")
@pytest.mark.parametrize("contract_path", get_example_contracts())
def test_compile_example_contract(get_contract, contract_path, request):
    for contract in PASSING:
        if contract_path.endswith(contract):
            break
    else:
        request.node.add_marker(pytest.mark.xfail(strict=True))

    with open(contract_path, "r") as f:
        source_code = f.read()

    _ = get_contract(source_code)
