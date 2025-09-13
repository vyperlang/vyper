#!/usr/bin/env python
"""Build docs and summarize warnings/errors.

Usage (Windows cmd):
  uv run python scripts/check_docs.py

Exit codes:
  0 - success, no warnings (or warnings allowed if --allow-warnings)
  1 - build error (sphinx failure)
  2 - warnings detected (default strict mode)
"""
from __future__ import annotations
import subprocess
import sys
import re
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
BUILD = DOCS / "_build" / "html"

RE_WARNING = re.compile(r"^(?P<file>.+?):(?P<line>\d+): (?P<type>WARNING|ERROR): (?P<msg>.*)$")


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def build_docs(language: str | None = None) -> str:
    env = os.environ.copy()
    if language:
        env["DOCS_LANGUAGE"] = language
    cmd = [sys.executable, "-m", "sphinx", "-n", "-W", "-b", "html", "docs", str(BUILD)]
    proc = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    return proc.stdout


def parse_warnings(output: str) -> dict:
    warnings = []
    errors = []
    for line in output.splitlines():
        m = RE_WARNING.match(line)
        if not m:
            continue
        entry = m.groupdict()
        if entry["type"] == "WARNING":
            warnings.append(entry)
        else:
            errors.append(entry)
    return {"warnings": warnings, "errors": errors}


def summarize(data: dict) -> str:
    parts = [
        f"Warnings: {len(data['warnings'])}",
        f"Errors: {len(data['errors'])}",
    ]
    sample = data["warnings"][:5]
    if sample:
        parts.append("Sample warnings:")
        for w in sample:
            parts.append(f"  {w['file']}:{w['line']}: {w['msg']}")
    return "\n".join(parts)


def main():
    allow_warnings = "--allow-warnings" in sys.argv
    langs = ["en"]
    # detect languages present besides en under docs/locale/<lang>/LC_MESSAGES
    if (DOCS / "locale").exists():
        # detect languages present besides en
        for p in (DOCS / "locale").iterdir():
            if p.is_dir() and (p / "LC_MESSAGES").exists() and p.name != "en":
                langs.append(p.name)
    all_data = {}
    aggregate_warnings = 0
    aggregate_errors = 0
    for lang in langs:
        print(f"== Building language: {lang}")
        out = build_docs(language=lang if lang != "en" else None)
        data = parse_warnings(out)
        all_data[lang] = data
        aggregate_warnings += len(data['warnings'])
        aggregate_errors += len(data['errors'])
        print(summarize(data))
    summary = {
        "languages": langs,
        "total_warnings": aggregate_warnings,
        "total_errors": aggregate_errors,
        "details": all_data,
    }
    print("== JSON summary ==")
    print(json.dumps(summary, indent=2))

    if aggregate_errors > 0:
        print("ERROR: Sphinx build produced errors.", file=sys.stderr)
        sys.exit(1)
    if aggregate_warnings > 0 and not allow_warnings:
        print("FAIL: Warnings detected (treating as error). Use --allow-warnings to ignore.", file=sys.stderr)
        sys.exit(2)
    print("SUCCESS: Docs build clean.")


if __name__ == "__main__":
    main()
