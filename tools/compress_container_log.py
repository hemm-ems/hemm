#!/usr/bin/env python3
"""Compress a noisy pytest/HA container log to failures-only view.

Reads stdin (or --file). Emits:
  - every line matching FAILED | ERROR | WARNING | Traceback | assert
  - N lines of leading context before each match (default 3)
  - the trailing pytest summary block (from "= short test summary info =" or
    "= FAILURES =" or the last "=== ... ===" header to EOF)

Drops everything else. Typical reduction: 2000+ lines → <50 lines.

Usage:
    make test-container-sc SC=SC-005 2>&1 | python3 tools/compress_container_log.py
    python3 tools/compress_container_log.py --file /tmp/some.log --context 5
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import deque
from pathlib import Path

MATCH = re.compile(r"FAILED|ERROR|WARNING|Traceback|^E\s|assert ")
SUMMARY_HEADER = re.compile(r"^=+ (short test summary info|FAILURES|ERRORS) =+")


def compress(lines: list[str], context: int) -> list[str]:
    out: list[str] = []
    buf: deque[str] = deque(maxlen=context)
    keep_until_eof = False
    emitted_idx: set[int] = set()

    for i, line in enumerate(lines):
        if not keep_until_eof and SUMMARY_HEADER.search(line):
            keep_until_eof = True
        if keep_until_eof:
            out.append(line)
            emitted_idx.add(i)
            continue
        if MATCH.search(line):
            start = max(0, i - len(buf))
            for j, b in enumerate(buf):
                idx = start + j
                if idx not in emitted_idx:
                    out.append(b)
                    emitted_idx.add(idx)
            if i not in emitted_idx:
                out.append(line)
                emitted_idx.add(i)
            buf.clear()
        else:
            buf.append(line)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", type=Path, default=None, help="log file (default: stdin)")
    p.add_argument("--context", type=int, default=3, help="leading-context lines (default 3)")
    args = p.parse_args()

    text = args.file.read_text(errors="replace") if args.file else sys.stdin.read()
    lines = text.splitlines(keepends=False)

    compressed = compress(lines, args.context)
    sys.stdout.write("\n".join(compressed))
    if compressed and not compressed[-1].endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.write(f"\n--- compressed {len(lines)} → {len(compressed)} lines ---\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
