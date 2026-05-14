"""Time-warp audit — fail if domain code reads time outside the `Clock`.

Forbids these calls in production source:

- `datetime.now(...)`
- `datetime.utcnow(...)`
- `time.time(...)`
- `time.monotonic(...)`
- `dt_util.utcnow(...)` (HA integration only)
- `dt_util.now(...)`     (HA integration only)

Whitelisted modules: the clock module itself, CLI entry points, and `__main__`.
Each repo points the script at its own source root via `--root` and may pass
additional `--allow` paths.

Exit code 0 = clean, 1 = violations found. Designed to be wired into
`make ci`.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


# Each entry: dotted suffix the call's `func` must end with.
# Matches whether the user wrote `datetime.now()` (from a `from datetime
# import datetime` import) or `datetime.datetime.now()` (from `import
# datetime`). Same for `dt_util.utcnow()` vs `homeassistant.util.dt.utcnow()`.
FORBIDDEN_SUFFIXES: tuple[tuple[str, ...], ...] = (
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("time", "time"),
    ("time", "monotonic"),
    ("dt_util", "utcnow"),
    ("dt_util", "now"),
    ("dt", "utcnow"),
    ("dt", "now"),
)


def _dotted_chain(node: ast.AST) -> tuple[str, ...] | None:
    """Return the dotted name chain for an Attribute/Name AST node.

    Examples (call's `func`):
      Name('foo')                       -> ('foo',)
      Attribute(Name('a'), 'b')         -> ('a', 'b')
      Attribute(Attribute(Name('a'), 'b'), 'c')  -> ('a', 'b', 'c')

    Returns None if the chain contains a non-name node (e.g. a subscript or
    a call), since those are not the patterns we audit.
    """
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        parts.reverse()
        return tuple(parts)
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.violations: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 — AST API
        chain = _dotted_chain(node.func)
        if chain is not None:
            for suffix in FORBIDDEN_SUFFIXES:
                if len(chain) >= len(suffix) and chain[-len(suffix):] == suffix:
                    self.violations.append((node.lineno, ".".join(suffix)))
                    break
        self.generic_visit(node)


def _is_whitelisted(file: Path, allow: list[Path]) -> bool:
    return any(file == a or a in file.parents for a in allow)


def _scan(root: Path, allow: list[Path]) -> list[tuple[Path, int, str]]:
    violations: list[tuple[Path, int, str]] = []
    for path in root.rglob("*.py"):
        if _is_whitelisted(path, allow):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as e:
            violations.append((path, e.lineno or 0, f"syntax-error: {e.msg}"))
            continue
        v = _Visitor(path)
        v.visit(tree)
        for line, label in v.violations:
            violations.append((path, line, label))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Source root to scan")
    parser.add_argument(
        "--allow",
        type=Path,
        action="append",
        default=[],
        help="File or directory to skip (repeatable)",
    )
    args = parser.parse_args()

    root: Path = args.root.resolve()
    allow: list[Path] = [a.resolve() for a in args.allow]

    if not root.exists():
        print(f"check_clock: root {root} does not exist", file=sys.stderr)
        return 2

    violations = _scan(root, allow)
    if not violations:
        print(f"check_clock: clean ({root})")
        return 0

    for path, line, label in violations:
        rel = path.relative_to(root.parent) if root.parent in path.parents else path
        print(f"{rel}:{line}: forbidden call `{label}(...)` — use injected Clock")
    print(f"\ncheck_clock: {len(violations)} violation(s) in {root}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
