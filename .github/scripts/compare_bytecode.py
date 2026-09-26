#!/usr/bin/env python3
"""Compare bytecode sizes between base and head and generate markdown report."""

import json
import sys

LEGACY_OPTS = ["O2", "Os"]
VENOM_OPTS = ["O2", "O3", "Os"]


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


def fmt_size(size, err):
    """Format size for display."""
    if err:
        return "❌"
    if size is None:
        return "-"
    return f"**{size}**"


def generate_report(base_path: str, head_path: str) -> str:
    with open(base_path) as f:
        base = json.load(f)["contracts"]
    with open(head_path) as f:
        head = json.load(f)["contracts"]

    # --- Changes section: venom deltas, legacy as reference ---
    change_rows = []
    all_files = sorted(set(base.keys()) | set(head.keys()))
    # errors (size=None) sort to top
    all_files.sort(key=lambda f: head.get(f, {}).get("venom", {}).get("O2", {}).get("size") or float('inf'), reverse=True)

    for file in all_files:
        base_data = base.get(file, {})
        head_data = head.get(file, {})

        # Check if venom changed
        venom_cells = []
        has_change = False
        for opt in VENOM_OPTS:
            b = base_data.get("venom", {}).get(opt, {})
            h = head_data.get("venom", {}).get(opt, {})
            cell, changed = fmt_delta(b.get("size"), h.get("size"), b.get("error"), h.get("error"))
            venom_cells.append(cell)
            has_change = has_change or changed

        if has_change:
            # Legacy columns: HEAD sizes as reference
            legacy_cells = []
            for opt in LEGACY_OPTS:
                h = head_data.get("legacy", {}).get(opt, {})
                legacy_cells.append(fmt_size(h.get("size"), h.get("error")))
            change_rows.append(f"| {file} | {' | '.join(legacy_cells)} | {' | '.join(venom_cells)} |")

    # --- Full table: just HEAD sizes, no deltas ---
    full_rows = []
    head_files = sorted(head.keys())
    # errors (size=None) sort to top
    head_files.sort(key=lambda f: head[f].get("venom", {}).get("O2", {}).get("size") or float('inf'), reverse=True)

    for file in head_files:
        head_data = head[file]
        legacy_cells = [fmt_size(head_data.get("legacy", {}).get(opt, {}).get("size"),
                                  head_data.get("legacy", {}).get(opt, {}).get("error"))
                        for opt in LEGACY_OPTS]
        venom_cells = [fmt_size(head_data.get("venom", {}).get(opt, {}).get("size"),
                                 head_data.get("venom", {}).get(opt, {}).get("error"))
                       for opt in VENOM_OPTS]
        full_rows.append(f"| {file} | {' | '.join(legacy_cells)} | {' | '.join(venom_cells)} |")

    # --- Build output ---
    legacy_hdrs = [f"legacy-{opt}" for opt in LEGACY_OPTS]
    venom_hdrs = [f"-{opt}" for opt in VENOM_OPTS]
    header = "| Contract | " + " | ".join(legacy_hdrs + venom_hdrs) + " |"
    sep = "|" + "|".join("-" * 10 for _ in range(len(legacy_hdrs) + len(venom_hdrs) + 1)) + "|"

    if change_rows:
        body = f"## 📊 Bytecode Size Changes (venom)\n\n{header}\n{sep}\n" + "\n".join(change_rows)
    else:
        body = "## 📊 Bytecode Size Changes (venom)\n\nNo changes detected."

    body += f"\n\n## Full bytecode sizes\n\n{header}\n{sep}\n"
    body += "\n".join(full_rows)

    return body


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <base.json> <head.json>", file=sys.stderr)
        sys.exit(1)
    print(generate_report(sys.argv[1], sys.argv[2]))
