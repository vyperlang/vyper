#!/usr/bin/env python3
"""
Format commit messages while preserving:
- List items (-, *, +, numbered)
- Code blocks
- Blank lines between paragraphs
- Intentional formatting
"""

import sys
import re
from textwrap import fill


def is_list_item(line):
    """Check if a line starts with a list marker."""
    stripped = line.lstrip()
    # bullet lists: -, *, +
    if stripped.startswith(("- ", "* ", "+ ")):
        return True
    # numbered lists: 1. 2. etc
    if re.match(r"^\d+\.\s", stripped):
        return True
    return False


def get_list_prefix(line):
    """Extract the list prefix and calculate continuation indent."""
    indent = len(line) - len(line.lstrip())
    stripped = line.lstrip()

    # bullet lists - continuation aligns with text after marker
    for marker in ["- ", "* ", "+ "]:
        if stripped.startswith(marker):
            prefix = " " * indent + marker
            content = stripped[len(marker) :].strip()
            # continuation lines indent by 2 spaces after the bullet
            cont_indent = " " * (indent + 2)
            return prefix, content, cont_indent

    # numbered lists - continuation aligns with text after number
    match = re.match(r"^(\d+\.)\s+", stripped)
    if match:
        number = match.group(1)
        prefix = " " * indent + number + " "
        content = stripped[match.end() :].strip()
        # continuation lines align with the start of text, not the number
        cont_indent = " " * (indent + len(number) + 1)
        return prefix, content, cont_indent

    return None, line.strip(), ""


def format_commit_message(text, width=72):
    """Format commit message text while preserving structure."""
    lines = text.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # preserve blank lines
        if not line.strip():
            result.append("")
            i += 1
            continue

        # handle code blocks
        if line.strip().startswith("```"):
            # preserve the opening fence
            result.append(line)
            i += 1

            # preserve all lines until closing fence
            while i < len(lines):
                result.append(lines[i])
                if lines[i].strip().startswith("```"):
                    i += 1
                    break
                i += 1
            continue

        # handle list items
        if is_list_item(line):
            prefix, content, cont_indent = get_list_prefix(line)

            # collect continuation lines for this list item
            j = i + 1
            while j < len(lines) and lines[j].strip() and not is_list_item(lines[j]):
                content += " " + lines[j].strip()
                j += 1

            # wrap the list item content
            wrapped = fill(
                content, width=width - len(prefix), initial_indent="", subsequent_indent=""
            )

            # add the prefix to the first line
            wrapped_lines = wrapped.split("\n")
            result.append(prefix + wrapped_lines[0])

            # add continuation lines with proper indent
            for wline in wrapped_lines[1:]:
                result.append(cont_indent + wline)

            i = j
            continue

        # handle regular paragraphs
        paragraph = []
        while (
            i < len(lines)
            and lines[i].strip()
            and not is_list_item(lines[i])
            and not lines[i].strip().startswith("```")
        ):
            paragraph.append(lines[i].strip())
            i += 1

        if paragraph:
            # join and wrap the paragraph
            text = " ".join(paragraph)
            wrapped = fill(text, width=width)
            result.extend(wrapped.split("\n"))

    return "\n".join(result)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Format commit messages")
    parser.add_argument(
        "file", nargs="?", default="commitmsg.txt", help="File to format (default: commitmsg.txt)"
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print formatted output without modifying the file",
    )

    args = parser.parse_args()

    # read from file or stdin
    if args.file == "-":
        text = sys.stdin.read()
    else:
        try:
            with open(args.file, "r") as f:
                text = f.read()
        except FileNotFoundError:
            print(f"Error: File '{args.file}' not found", file=sys.stderr)
            sys.exit(1)

    # format the message
    formatted = format_commit_message(text)

    # output
    if args.dry_run or args.file == "-":
        # dry run or stdin: just print
        print(formatted)
    else:
        # write back to file and print
        with open(args.file, "w") as f:
            f.write(formatted)
        print(formatted)


if __name__ == "__main__":
    main()
