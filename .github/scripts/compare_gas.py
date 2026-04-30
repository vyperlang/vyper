#!/usr/bin/env python3
"""Compare gas usage between base and head and generate markdown report."""

import json
import sys


def fmt_row(test, base_entry, head_entry):
    # returns (display_row, delta_for_sorting, kind) where kind in
    # {"new", "deleted", "broke", "fixed", "regression", "improvement", "unchanged"}
    base_gas = base_entry.get("gas") if base_entry else None
    head_gas = head_entry.get("gas") if head_entry else None
    base_status = base_entry.get("status") if base_entry else None
    head_status = head_entry.get("status") if head_entry else None

    if base_entry is None and head_entry is not None:
        return f"| {test} | - | ➕ **{head_gas}** | new |", 0, "new"
    if base_entry is not None and head_entry is None:
        return f"| {test} | **{base_gas}** | - | 🗑️ |", 0, "deleted"
    # status flips: forge marks suite-level breakage at the test level too
    if base_status == "Success" and head_status != "Success":
        return f"| {test} | **{base_gas}** | 💥 | failing ({head_status}) |", 0, "broke"
    if base_status != "Success" and head_status == "Success":
        return f"| {test} | ❌ | 🔧 **{head_gas}** | fixed |", 0, "fixed"
    if base_gas is None or head_gas is None:
        return None
    if base_gas == head_gas:
        return None
    delta = head_gas - base_gas
    sign = "+" if delta > 0 else ""
    icon = "🔴" if delta > 0 else "🟢"
    return (
        f"| {test} | **{base_gas}** | **{head_gas}** | {icon}{sign}{delta} |",
        delta,
        ("regression" if delta > 0 else "improvement"),
    )


def generate_report(base_path, head_path):
    with open(base_path) as f:
        base = json.load(f)["tests"]
    with open(head_path) as f:
        head = json.load(f)["tests"]

    all_tests = sorted(set(base.keys()) | set(head.keys()))
    rows = []
    regressions = []
    improvements = []
    new_count = 0
    deleted_count = 0
    broke_count = 0
    fixed_count = 0

    for test in all_tests:
        result = fmt_row(test, base.get(test), head.get(test))
        if result is None:
            continue
        row, delta, kind = result
        rows.append((row, delta, kind, test))
        if kind == "regression":
            regressions.append((test, delta))
        elif kind == "improvement":
            improvements.append((test, delta))
        elif kind == "new":
            new_count += 1
        elif kind == "deleted":
            deleted_count += 1
        elif kind == "broke":
            broke_count += 1
        elif kind == "fixed":
            fixed_count += 1

    rows.sort(key=lambda r: abs(r[1]), reverse=True)

    header = "| Test | Base Gas | Head Gas | Delta |"
    sep = "|---|---|---|---|"

    if rows:
        body = "## Gas Changes\n\n" + header + "\n" + sep + "\n" + "\n".join(r[0] for r in rows)
    else:
        body = "## Gas Changes\n\nNo changes detected."

    total = len(set(base.keys()) | set(head.keys()))
    changed = len(rows)
    top_reg = max(regressions, key=lambda r: r[1]) if regressions else None
    top_imp = min(improvements, key=lambda r: r[1]) if improvements else None

    body += "\n\n## Summary\n\n"
    body += f"- Total tests measured: {total}\n"
    body += f"- Changed: {changed}\n"
    body += f"- Regressions (gas up): {len(regressions)}\n"
    body += f"- Improvements (gas down): {len(improvements)}\n"
    body += f"- New tests: {new_count}\n"
    body += f"- Deleted tests: {deleted_count}\n"
    body += f"- Newly failing: {broke_count}\n"
    body += f"- Newly passing: {fixed_count}\n"
    if top_reg:
        body += f"- Top regression: `{top_reg[0]}` (+{top_reg[1]})\n"
    if top_imp:
        body += f"- Top improvement: `{top_imp[0]}` ({top_imp[1]})\n"

    return body


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <base.json> <head.json>", file=sys.stderr)
        sys.exit(1)
    print(generate_report(sys.argv[1], sys.argv[2]))
