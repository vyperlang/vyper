import os
import pytest
import glob
from pathlib import Path


pytestmark = pytest.mark.hevm

# List of contracts to exclude from testing
EXCLUDED_CONTRACTS = [
    "examples/wallet/wallet.vy", # CopySlice with a symbolically sized region not currently implemented
    "examples/name_registry/name_registry.vy", # CopySlice with a symbolically sized region not currently implemented
    "examples/auctions/blind_auction.vy", # 1x -> SMT result timeout/unknown for TIMEOUT=600
    "examples/tokens/ERC1155ownable.vy", # long time to finish
    "examples/voting/ballot.vy", # long time to finish
    "examples/tokens/ERC721.vy" # long time to finish
    "examples/crowdfund.vy"  # ??
]


def get_example_contracts():
    root = Path(__file__).parent.parent.parent.parent.parent
    examples_dir = root / "examples"
    vy_file_paths = [str(p) for p in examples_dir.rglob("*.vy")]
    ignored_set = [str(root / path) for path in EXCLUDED_CONTRACTS]
    filtered = [path for path in vy_file_paths if path not in ignored_set]
    return filtered

@pytest.mark.parametrize("contract_path", get_example_contracts())
def test_compile_example_contract(get_contract, contract_path):
    with open(contract_path, 'r') as f:
        source_code = f.read()

    _ = get_contract(source_code)