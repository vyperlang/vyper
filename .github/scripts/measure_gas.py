#!/usr/bin/env python3
"""Measure gas usage of snekmate's foundry test suite under the Venom backend.

Usage:
    python .github/scripts/measure_gas.py --snekmate-dir /path/to/snekmate
    python .github/scripts/measure_gas.py --snekmate-dir /path/to/snekmate --include-fuzz
"""

import argparse
import json
import os
import subprocess
import sys


def extract_gas(kind):
    # forge --json reports kind as {"Unit": {"gas": N}} | {"Fuzz": {"median_gas": N, ...}} |
    # {"Invariant": {...}}; pick the one numeric field that represents this run's gas
    if not isinstance(kind, dict):
        return None
    for v in kind.values():
        if not isinstance(v, dict):
            continue
        if "gas" in v:
            return v["gas"]
        # fuzz/invariant have no scalar gas; median is the most stable representative
        if "median_gas" in v:
            return v["median_gas"]
    return None


def run_forge(snekmate_dir):
    env = os.environ.copy()
    # default-venom is snekmate's profile that enables experimental_codegen=True (Venom backend)
    env["FOUNDRY_PROFILE"] = "default-venom"
    # pin fuzz/invariant seeds: identical compiled code must produce identical
    # gas across runs, otherwise the diff drowns in fuzzer-input noise
    env["FOUNDRY_FUZZ_SEED"] = "0x1"
    env["FOUNDRY_INVARIANT_SEED"] = "0x1"
    proc = subprocess.run(
        ["forge", "test", "--json"], cwd=snekmate_dir, env=env, capture_output=True, text=True
    )
    return proc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snekmate-dir", required=True, help="Path to snekmate checkout")
    parser.add_argument(
        "--include-fuzz", action="store_true", help="Include testFuzz_/invariant_ tests (noisy)"
    )
    args = parser.parse_args()

    print(f"Running forge test in {args.snekmate_dir}...", file=sys.stderr)
    proc = run_forge(args.snekmate_dir)

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print("forge produced no parseable JSON on stdout", file=sys.stderr)
        print("--- stderr ---", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        print("--- stdout (head) ---", file=sys.stderr)
        print(proc.stdout[:2000], file=sys.stderr)
        sys.exit(proc.returncode if proc.returncode != 0 else 1)

    tests = {}
    total = 0
    passing = 0
    failing = 0
    skipped_fuzz = 0
    failing_names = []

    for suite_path, suite in data.items():
        contract_name = suite_path.split(":", 1)[1] if ":" in suite_path else suite_path
        for test_name, result in suite.get("test_results", {}).items():
            total += 1
            base_name = test_name.split("(", 1)[0]
            if not args.include_fuzz and (
                base_name.startswith("testFuzz_") or base_name.startswith("invariant_")
            ):
                skipped_fuzz += 1
                continue
            status = result.get("status", "Unknown")
            full_name = f"{contract_name}:{test_name}"
            if status != "Success":
                failing += 1
                failing_names.append(full_name)
                tests[full_name] = {"gas": None, "status": status}
                continue
            gas = extract_gas(result.get("kind"))
            tests[full_name] = {"gas": gas, "status": status}
            passing += 1

    output = {
        "tests": tests,
        "metadata": {
            "total_tests_seen": total,
            "passing": passing,
            "failing": failing,
            "skipped_fuzz": skipped_fuzz,
            "failing_tests": failing_names,
        },
    }

    if proc.returncode != 0:
        print(f"forge exited {proc.returncode}; reporting {failing} failing tests", file=sys.stderr)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
