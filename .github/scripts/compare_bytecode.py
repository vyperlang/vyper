#!/usr/bin/env python3
"""Compare bytecode sizes between base and head and generate markdown report."""

import json
import sys

CODEGENS = ["legacy", "venom"]
OPT_LEVELS = ["O2", "Os"]


def fmt_delta(base_size, head_size, base_err, head_err):
    """Format delta between base and head. Returns (display_str, has_change)."""
    if base_err and head_err:
        return "❌", False
    if base_err and not head_err:
        return f"🔧 **{head_size}**", True
    if not base_err and head_err:
        return "💥", True
    if base_size is None and head_size is not None:
        return f"➕ **{head_size}**", True
    if base_size is not None and head_size is None:
        return "🗑️", True
    if base_size == head_size:
        return f"**{head_size}**", False
    delta = head_size - base_size
    sign = "+" if delta > 0 else ""
    icon = "🔴" if delta > 0 else "🟢"
    return f"**{head_size}** ({icon}{sign}{delta})", True


def generate_report(base_path: str, head_path: str) -> str:
    with open(base_path) as f:
        base = json.load(f)["contracts"]
    with open(head_path) as f:
        head = json.load(f)["contracts"]

    change_rows = []
    full_rows = []

    # Sort by largest bytecode size on head (venom O2)
    all_files = sorted(set(base.keys()) | set(head.keys()))
    all_files.sort(key=lambda f: head.get(f, {}).get("venom", {}).get("O2", {}).get("size") or 0, reverse=True)

    for file in all_files:
        base_data = base.get(file, {})
        head_data = head.get(file, {})

        cells = []
        has_change = False

        for codegen in CODEGENS:
            for opt in OPT_LEVELS:
                b = base_data.get(codegen, {}).get(opt, {})
                h = head_data.get(codegen, {}).get(opt, {})
                cell, changed = fmt_delta(b.get("size"), h.get("size"), b.get("error"), h.get("error"))
                cells.append(cell)
                has_change = has_change or changed

        row = f"| {file} | {' | '.join(cells)} |"
        full_rows.append(row)
        if has_change:
            change_rows.append(row)

    # Header: Contract | legacy-O2 | legacy-Os | venom-O2 | venom-Os
    columns = [f"{cg}-{opt}" for cg in CODEGENS for opt in OPT_LEVELS]
    header = "| Contract | " + " | ".join(columns) + " |"
    sep = "|" + "|".join("-" * 12 for _ in range(len(columns) + 1)) + "|"

    # Changes section
    if change_rows:
        body = f"## 📊 Bytecode Size Changes\n\n{header}\n{sep}\n" + "\n".join(change_rows)
    else:
        body = "## 📊 Bytecode Size Changes\n\nNo changes detected."

    # Full table section
    body += f"\n\n## Full bytecode sizes\n\n{header}\n{sep}\n"
    body += "\n".join(full_rows)

    return body


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <base.json> <head.json>", file=sys.stderr)
        sys.exit(1)
    print(generate_report(sys.argv[1], sys.argv[2]))
