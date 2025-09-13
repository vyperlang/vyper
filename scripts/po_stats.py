#!/usr/bin/env python
"""Scan locale PO files and report translation progress.

Usage:
  uv run python scripts/po_stats.py

Outputs JSON summary with per-language counts:
  total, translated, untranslated, fuzzy.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = ROOT / "docs" / "locale"
PO_GLOB = "**/*.po"

RE_MSGID = re.compile(r'^msgid\s+"')
RE_MSGSTR = re.compile(r'^msgstr(?:\[\d+\])?\s+"')
RE_FUZZY = re.compile(r'^#,.*fuzzy')

# Simple PO parser (sufficient for statistics)

def parse_po(path: Path):
    entries = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    current = {"msgid": [], "msgstr": [], "fuzzy": False}
    state = None
    for line in lines:
        if line.startswith('#,') and 'fuzzy' in line:
            current['fuzzy'] = True
        if line.startswith('msgid '):
            # new entry
            if state is not None:
                entries.append(current)
                current = {"msgid": [], "msgstr": [], "fuzzy": False}
            state = 'msgid'
            current['msgid'] = [line]
        elif line.startswith('msgstr'):
            state = 'msgstr'
            current['msgstr'] = [line]
        else:
            if state == 'msgid' and (line.startswith('"')):
                current['msgid'].append(line)
            elif state == 'msgstr' and (line.startswith('"')):
                current['msgstr'].append(line)
    if state is not None:
        entries.append(current)
    # skip header (first entry usually empty msgid)
    real = [e for e in entries if not (len(''.join(e['msgid']).strip()) <= len('msgid ""'))]
    translated = 0
    untranslated = 0
    fuzzy = 0
    for e in real:
        msgstr_body = ''.join(e['msgstr'])
        if e['fuzzy']:
            fuzzy += 1
        if 'msgstr ""' in msgstr_body:
            untranslated += 1
        else:
            translated += 1
    return {
        'file': str(path.relative_to(ROOT)),
        'total': len(real),
        'translated': translated,
        'untranslated': untranslated,
        'fuzzy': fuzzy,
    }

def main():
    if not LOCALES_DIR.exists():
        print(json.dumps({'error': 'no locales dir'}, indent=2))
        return
    lang_stats = {}
    for lang_dir in LOCALES_DIR.iterdir():
        if not lang_dir.is_dir():
            continue
        lang = lang_dir.name
        po_files = sorted((lang_dir / 'LC_MESSAGES').glob('*.po')) if (lang_dir / 'LC_MESSAGES').exists() else []
        totals = {'files': 0, 'total': 0, 'translated': 0, 'untranslated': 0, 'fuzzy': 0, 'files_detail': []}
        for po in po_files:
            data = parse_po(po)
            totals['files'] += 1
            for k in ('total', 'translated', 'untranslated', 'fuzzy'):
                totals[k] += data[k]
            totals['files_detail'].append(data)
        if totals['files']:
            totals['progress'] = 0 if totals['total']==0 else round(100 * totals['translated']/totals['total'], 2)
        lang_stats[lang] = totals
    print(json.dumps({'languages': lang_stats}, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
