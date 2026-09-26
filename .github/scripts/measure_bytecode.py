#!/usr/bin/env python3
"""Measure bytecode sizes for thirdparty example contracts.

Usage:
    python .github/scripts/measure_bytecode.py            # all contracts
    python .github/scripts/measure_bytecode.py --limit 3  # first 3 only (for local testing)
"""

import argparse
import glob
import json
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path

import vyper.compiler as compiler
from vyper.compiler.settings import OptimizationLevel, Settings

DIR_PATH = Path("tests/functional/examples/thirdparty")

# legacy: O2, Os only
# venom: O2, O3, Os
LEGACY_OPT_LEVELS = {"O2": OptimizationLevel.GAS, "Os": OptimizationLevel.CODESIZE}
VENOM_OPT_LEVELS = {"O2": OptimizationLevel.GAS, "O3": OptimizationLevel.O3, "Os": OptimizationLevel.CODESIZE}


def get_example_vy_filenames(limit: int | None = None):
    files = sorted(glob.glob("**/*.vy", root_dir=DIR_PATH, recursive=True))
    return files[:limit] if limit else files


def compile_one(source_code: str, opt_level: OptimizationLevel, experimental: bool) -> tuple[int | None, str | None]:
    """Compile with given settings. Returns (size, error)."""
    try:
        settings = Settings(experimental_codegen=experimental, optimize=opt_level)
        result = compiler.compile_code(source_code, settings=settings, output_formats=["bytecode"])
        bytecode = result.get("bytecode", "")
        size = (len(bytecode) - 2) // 2 if bytecode.startswith("0x") else len(bytecode) // 2
        return size, None
    except Exception as e:
        return None, str(e)


def measure_contract(filename: str) -> tuple[str, dict]:
    """Compile a contract with all optimization levels. Returns (filename, results)."""
    try:
        with open(DIR_PATH / filename) as f:
            source_code = f.read()
    except Exception as e:
        error = {"size": None, "error": str(e)}
        return filename, {
            "legacy": {opt: error for opt in LEGACY_OPT_LEVELS},
            "venom": {opt: error for opt in VENOM_OPT_LEVELS},
        }

    results = {
        "legacy": {
            name: dict(zip(["size", "error"], compile_one(source_code, opt, False)))
            for name, opt in LEGACY_OPT_LEVELS.items()
        },
        "venom": {
            name: dict(zip(["size", "error"], compile_one(source_code, opt, True)))
            for name, opt in VENOM_OPT_LEVELS.items()
        },
    }
    return filename, results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Only compile first N contracts (for local testing)")
    args = parser.parse_args()

    files = get_example_vy_filenames(args.limit)
    total = len(files)

    print(f"Compiling {total} contracts with {cpu_count()} workers...", file=sys.stderr)

    file_index = {f: i for i, f in enumerate(files, 1)}
    results = {}
    with Pool() as pool:
        for filename, data in pool.imap_unordered(measure_contract, files):
            print(f"[{file_index[filename]}/{total}] {filename}", file=sys.stderr)
            results[filename] = data

    print(json.dumps({"contracts": results}, indent=2))


if __name__ == "__main__":
    main()
