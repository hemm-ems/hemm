"""Branding and HA identifier audit for the HEMM repos.

Pure stdlib so it can run from any child repo without a virtual environment.
It intentionally reports known Phase 3 rename debt today.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_LITERALS = (
    "github.com/swifty99",
    "api.github.com/repos/swifty99",
    "github.com/hemm-energy",
    "@hemm-energy",
    "hactl_companion",
)

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    "htmlcov",
}
SKIP_FILES = {
    Path("tools/branding_audit.py"),
    Path("tests/test_branding_audit.py"),
}
TEXT_SUFFIXES = {
    ".c",
    ".cfg",
    ".h",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

CUSTOM_COMPONENT_RE = re.compile(r"custom_components/([A-Za-z0-9_-]+)")
DOMAIN_ASSIGN_RE = re.compile(r"^DOMAIN\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
AUTOMATION_ID_RE = re.compile(r"^\s*-\s*id:\s*['\"]?([^'\"\s#]+)", re.MULTILINE)
UNIQUE_ID_ASSIGN_RE = re.compile(r"_attr_unique_id\s*=\s*(?P<value>.+)")


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    code: str
    message: str

    def render(self, root: Path) -> str:
        rel = self.path.relative_to(root) if self.path.is_relative_to(root) else self.path
        return f"{rel}:{self.line}: {self.code}: {self.message}"


def iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and (path.suffix in TEXT_SUFFIXES or path.name == "Makefile"):
            files.append(path)
    return files


def line_for(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def literal_value(node: ast.AST, domain: str = "hemm") -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif (
                isinstance(value, ast.FormattedValue)
                and isinstance(value.value, ast.Name)
                and value.value.id == "DOMAIN"
            ):
                parts.append(domain)
            else:
                return None
        return "".join(parts)
    return None


def is_entry_scoped_unique_id(node: ast.AST) -> bool:
    """Return true for HA-stable unique IDs scoped by config entry."""
    if not isinstance(node, ast.JoinedStr) or not node.values:
        return False
    first = node.values[0]
    return (
        isinstance(first, ast.FormattedValue)
        and isinstance(first.value, ast.Attribute)
        and first.value.attr == "entry_id"
    )


def audit_text(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for literal in FORBIDDEN_LITERALS:
        for match in re.finditer(re.escape(literal), text):
            findings.append(
                Finding(path, line_for(text, match.start()), "forbidden-brand", f"forbidden reference {literal!r}")
            )

    for match in CUSTOM_COMPONENT_RE.finditer(text):
        component = match.group(1)
        if component != "hemm":
            findings.append(
                Finding(
                    path,
                    line_for(text, match.start()),
                    "custom-component-domain",
                    f"custom_components/{component} is not custom_components/hemm",
                )
            )

    return findings


def audit_custom_component_path(path: Path) -> list[Finding]:
    parts = path.parts
    findings: list[Finding] = []
    for index, part in enumerate(parts[:-1]):
        if part != "custom_components":
            continue
        component = parts[index + 1]
        if component != "hemm":
            findings.append(
                Finding(
                    path,
                    1,
                    "custom-component-domain",
                    f"custom_components/{component} is not custom_components/hemm",
                )
            )
    return findings


def audit_manifest(path: Path, text: str) -> list[Finding]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if "domain" in data and data["domain"] != "hemm":
        return [Finding(path, 1, "manifest-domain", f"manifest domain is {data['domain']!r}, expected 'hemm'")]
    return []


def audit_const_domain(path: Path, text: str) -> list[Finding]:
    match = DOMAIN_ASSIGN_RE.search(text)
    if not match or match.group(1) == "hemm":
        return []
    return [Finding(path, line_for(text, match.start()), "const-domain", "const.py DOMAIN must be 'hemm'")]


def audit_python_identifiers(path: Path, text: str) -> list[Finding]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    domain = "hemm"
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
        attrs = [target.attr for target in node.targets if isinstance(target, ast.Attribute)]
        value = literal_value(node.value, domain)

        if "DOMAIN" in targets and value is not None:
            domain = value

        for target in targets:
            if target.startswith("EVENT_") and value is not None and not value.startswith("hemm_"):
                findings.append(
                    Finding(path, node.lineno, "event-prefix", f"{target} value {value!r} must start with 'hemm_'")
                )

        if "_attr_unique_id" in attrs:
            if value is None:
                line = text.splitlines()[node.lineno - 1]
                match = UNIQUE_ID_ASSIGN_RE.search(line)
                raw = match.group("value").strip() if match else line.strip()
                if not (
                    raw.startswith('f"{DOMAIN}_')
                    or raw.startswith("f'{DOMAIN}_")
                    or is_entry_scoped_unique_id(node.value)
                ):
                    findings.append(
                        Finding(
                            path,
                            node.lineno,
                            "unique-id-prefix",
                            "_attr_unique_id expression must start with hemm_ or DOMAIN_",
                        )
                    )
            elif not value.startswith("hemm_"):
                findings.append(
                    Finding(path, node.lineno, "unique-id-prefix", f"unique id {value!r} must start with 'hemm_'")
                )
    return findings


def audit_automation_ids(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in AUTOMATION_ID_RE.finditer(text):
        automation_id = match.group(1)
        if not automation_id.startswith("hemm_"):
            findings.append(
                Finding(
                    path,
                    line_for(text, match.start()),
                    "automation-id-prefix",
                    f"automation id {automation_id!r} must start with 'hemm_'",
                )
            )
    return findings


def audit_path(root: Path) -> list[Finding]:
    root = root.resolve()
    findings: list[Finding] = []
    for path in iter_text_files(root):
        rel = path.relative_to(root)
        if rel in SKIP_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(audit_custom_component_path(path))
        findings.extend(audit_text(path, text))
        if path.name == "manifest.json":
            findings.extend(audit_manifest(path, text))
        if path.name == "const.py":
            findings.extend(audit_const_domain(path, text))
        if path.suffix == ".py":
            findings.extend(audit_python_identifiers(path, text))
        path_text = path.as_posix()
        if path.suffix in {".yaml", ".yml"} and (
            "custom_components/hemm/examples" in path_text or "/tests/sim/houses/" in path_text
        ):
            findings.extend(audit_automation_ids(path, text))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit HEMM branding and generated HA identifiers.")
    core_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--root",
        type=Path,
        action="append",
        default=None,
        help=(
            "Repo root to scan (repeatable). Default: the core repo and the "
            "sibling ha-hemm checkout."
        ),
    )
    args = parser.parse_args(argv)

    roots = (
        [r.resolve() for r in args.root]
        if args.root
        else [core_root, core_root.parent / "ha-hemm"]
    )

    total = 0
    for root in roots:
        if not root.is_dir():
            continue
        findings = audit_path(root)
        total += len(findings)
        for finding in findings:
            print(finding.render(root))
    if total:
        print(f"\nFAIL: {total} branding audit finding(s)", file=sys.stderr)
        return 1
    print("branding audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
