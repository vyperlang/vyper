#!/usr/bin/env python3
"""Measure bytecode sizes for thirdparty example contracts with experimental codegen.

Usage:
    python .github/scripts/measure_bytecode.py            # all contracts
    python .github/scripts/measure_bytecode.py --limit 3  # first 3 only (for local testing)
"""

import argparse
import glob
import json
import sys
from pathlib import Path

import vyper.compiler as compiler
from vyper.compiler.settings import OptimizationLevel, Settings

DIR_PATH = Path("tests/functional/examples/thirdparty")

OPT_LEVELS = {
    "O2": OptimizationLevel.GAS,  # O2/gas are equivalent
    "O3": OptimizationLevel.O3,
    "Os": OptimizationLevel.CODESIZE,  # Os/codesize are equivalent
}


def get_example_vy_filenames(limit: int | None = None):
    files = sorted(glob.glob("**/*.vy", root_dir=DIR_PATH, recursive=True))
    return files[:limit] if limit else files


def compile_with_opt(source_code: str, opt_level: OptimizationLevel) -> tuple[int | None, str | None]:
    """Compile with experimental codegen and given optimization level. Returns (size, error)."""
    try:
        settings = Settings(experimental_codegen=True, optimize=opt_level)
        result = compiler.compile_code(source_code, settings=settings, output_formats=["bytecode"])
        bytecode = result.get("bytecode", "")
        size = (len(bytecode) - 2) // 2 if bytecode.startswith("0x") else len(bytecode) // 2
        return size, None
    except Exception as e:
        return None, str(e)


def measure_contract(filename: str) -> dict:
    """Compile a contract with all optimization levels."""
    try:
        with open(DIR_PATH / filename) as f:
            source_code = f.read()
    except Exception as e:
        return {name: {"size": None, "error": str(e)} for name in OPT_LEVELS}

    return {
        name: dict(zip(["size", "error"], compile_with_opt(source_code, opt)))
        for name, opt in OPT_LEVELS.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Only compile first N contracts (for local testing)")
    args = parser.parse_args()

    files = get_example_vy_filenames(args.limit)
    results = {}
    for i, filename in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {filename}", file=sys.stderr)
        results[filename] = measure_contract(filename)
    print(json.dumps({"contracts": results}, indent=2))


if __name__ == "__main__":
    main()
