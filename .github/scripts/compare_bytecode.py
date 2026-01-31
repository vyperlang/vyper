#!/usr/bin/env python3
"""Compare bytecode sizes between base and head and generate markdown report."""

import json
import sys

OPT_LEVELS = ["O2", "O3", "Os"]


def fmt_delta(base_size, head_size, base_err, head_err):
    """Format delta between base and head. Returns (display_str, has_change)."""
    if base_err and head_err:
        return "❌", False
    if base_err and not head_err:
        return f"🔧 {head_size}", True
    if not base_err and head_err:
        return "💥", True
    if base_size is None and head_size is not None:
        return f"➕ {head_size}", True
    if base_size is not None and head_size is None:
        return "🗑️", True
    if base_size == head_size:
        return str(head_size), False
    delta = head_size - base_size
    sign = "+" if delta > 0 else ""
    icon = "🔴" if delta > 0 else "🟢"
    return f"{head_size} ({icon}{sign}{delta})", True


def generate_report(base_path: str, head_path: str) -> str:
    with open(base_path) as f:
        base = json.load(f)["contracts"]
    with open(head_path) as f:
        head = json.load(f)["contracts"]

    rows = []

    for file in sorted(set(base.keys()) | set(head.keys())):
        base_data = base.get(file, {})
        head_data = head.get(file, {})

        cells = []
        has_change = False

        for opt in OPT_LEVELS:
            b = base_data.get(opt, {})
            h = head_data.get(opt, {})
            cell, changed = fmt_delta(b.get("size"), h.get("size"), b.get("error"), h.get("error"))
            cells.append(cell)
            has_change = has_change or changed

        if has_change:
            rows.append(f"| {file} | {' | '.join(cells)} |")

    if rows:
        header = "| Contract | " + " | ".join(f"-{opt}" for opt in OPT_LEVELS) + " |"
        sep = "|" + "|".join("-" * 10 for _ in range(len(OPT_LEVELS) + 1)) + "|"
        body = f"## 📊 Bytecode Size Changes (venom)\n\n{header}\n{sep}\n" + "\n".join(rows)
    else:
        body = "## 📊 Bytecode Size Changes (venom)\n\nNo changes detected."

    return body


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <base.json> <head.json>", file=sys.stderr)
        sys.exit(1)
    print(generate_report(sys.argv[1], sys.argv[2]))
