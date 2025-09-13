#!/usr/bin/env python3
"""
Update README.md translation progress section based on scripts/po_stats.py output.

Behavior:
- Reads po_stats.json (or invokes po_stats.py if missing)
- Generates a markdown table of translation progress per language
- Replaces or appends the section between markers:
  <!-- START:PO_STATS --> ... <!-- END:PO_STATS -->
- Writes a copy of the table to po_stats_table.md for CI summary
- Exits with code 0; prints a short status line
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PO_STATS_JSON = ROOT / 'po_stats.json'
PO_STATS_SCRIPT = ROOT / 'scripts' / 'po_stats.py'
README = ROOT / 'README.md'
TABLE_MD = ROOT / 'po_stats_table.md'

START = '<!-- START:PO_STATS -->'
END = '<!-- END:PO_STATS -->'


def ensure_po_stats() -> dict:
    if not PO_STATS_JSON.exists():
        proc = subprocess.run(
            ['python', str(PO_STATS_SCRIPT)],
            check=True,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        PO_STATS_JSON.write_text(proc.stdout, encoding='utf-8')
    with PO_STATS_JSON.open('r', encoding='utf-8') as f:
        return json.load(f)


def render_table(data: dict) -> str:
    langs = data.get('languages', {}) or {}
    lines = []
    lines.append('')
    lines.append('进度统计（自动生成）')
    lines.append('')
    lines.append('| 语言 | PO文件 | 总条目 | 已翻译 | Fuzzy | 未翻译 | 完成度 |')
    lines.append('| --- | ---: | ---: | ---: | ---: | ---: | ---: |')
    for lang in sorted(langs.keys()):
        stats = langs.get(lang, {}) or {}
        files = stats.get('files', 0)
        total = stats.get('total', 0)
        translated = stats.get('translated', 0)
        fuzzy = stats.get('fuzzy', 0)
        untranslated = stats.get('untranslated', 0)
        progress = stats.get('progress', 0)
        lines.append(
            f"| {lang} | {files} | {total} | {translated} | {fuzzy} | {untranslated} | {progress}% |"
        )
    return '\n'.join(lines) + '\n'


def update_readme(table_md: str) -> bool:
    content = README.read_text(encoding='utf-8') if README.exists() else ''
    section = f"\n{START}\n{table_md}{END}\n"
    if START in content and END in content:
        pattern = re.compile(re.escape(START) + r"[\s\S]*?" + re.escape(END), re.MULTILINE)
        new_content = pattern.sub(section.strip(), content).rstrip() + "\n"
    else:
        # Append to end with a heading if README is mostly empty
        prefix = '' if content.endswith('\n') or content == '' else '\n'
        new_content = content + prefix + section
    if new_content != content:
        README.write_text(new_content, encoding='utf-8')
        return True
    return False


def main() -> None:
    data = ensure_po_stats()
    table = render_table(data)
    TABLE_MD.write_text(table, encoding='utf-8')
    changed = update_readme(table)
    print(f"README updated: {'yes' if changed else 'no'}")


if __name__ == '__main__':
    main()
