"""Requirement-coverage audit — link spec FRs to the tests that exercise them.

Reads every `specs/NNN-slug/spec.md`, extracts Functional Requirements and their
declared status (done / partial / todo), then scans the test trees for
references back to those FRs. Produces a traceability matrix and, in `--check`
mode, fails the build when a requirement *claimed* as done has no test pointing
at it — the "green-by-assertion" lie the concept review warns about.

Reference convention (recognized anywhere in a test file):

    @pytest.mark.req("002:FR-009")          # idiomatic, also enables `pytest -m req`
    # REQ: 002:FR-009                        # zero-config comment, no marker registration

`NNN` is the spec's directory number (stable across renames); `FR-MMM` is the
requirement id within that spec. Multiple ids may be comma-separated:

    @pytest.mark.req("002:FR-010", "002:FR-011")
    # REQ: 002:FR-010, 002:FR-011

Test tiers
----------
Each covering test is classified by its file path: a test under an `integration`
directory (e.g. `ha-hemm/tests/integration/`) is an *integration* test (runs
against a real Home Assistant container); everything else is a *unit* test.

Each FR declares its *intended* tier in `spec.md`, right after the status tag:

    - **FR-007** `✅ done`: ...           # intended tier = integration (default)
    - **FR-006** `✅ done` `unit`: ...    # intended tier = unit (pure logic)

The gate requires a `done` FR whose intended tier is `integration` to be backed by
at least one integration test — a unit test alone does not satisfy it. A `done` FR
tagged `unit` passes with any referencing test. This makes "covered" mean "proven
end-to-end in Docker" by default, not "asserted by a shallow unit test".

Exit code 0 = ok (or report-only), 1 = coverage gate failed / structural error.
Pure standard library so it runs with no venv, like `tools/check_clock.py`.

Layout
------
This tool lives in the *core* repo (`hemm`) alongside `specs/`. It scans the
core repo's own `tests/` and the sibling `ha-hemm` checkout's `tests/`. Locally
`ha-hemm` is a sibling directory (`../ha-hemm`); in CI it is checked out next to
the core repo with the same relative layout. Override the ha-hemm location with
`--ha-tests` if needed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# A requirement line in a spec, e.g.
#   - **FR-013** `⬜ todo`: The validator MUST warn ...
#   - **FR-006** `✅ done` `unit`: Synthetic generation MUST be deterministic ...
# The optional trailing `unit`/`integration` token sets the intended tier
# (default: integration).
_FR_LINE = re.compile(
    r"\*\*FR-(?P<num>\d+)\*\*\s*`?\s*(?:✅|🔶|⬜)?\s*(?P<status>done|partial|todo)\b"
    r"`?\s*(?:`(?P<tier>unit|integration)`)?"
    r"\s*(?:`SR-(?P<sr>\d+)`)?",
)

# A System-Requirement header in specs/requirements.md, e.g.
#   ## SR-004 — A central MILP solver produces the plan (the default backend)
_SR_HEADER = re.compile(r"^##\s+SR-(?P<num>\d+)\s+—\s+(?P<title>.+?)\s*$")

# A reference to a requirement from a test file. Captures the whole id list so
# the caller can split on commas: "002:FR-010", "002:FR-011".
_REQ_REF = re.compile(r"""(?:@pytest\.mark\.req\(|#\s*REQ:)\s*(?P<ids>[^)\n]+)""")

# A single "NNN:FR-MMM" token inside a reference.
_REQ_ID = re.compile(r"(?P<spec>\d{3})\s*:\s*FR-(?P<num>\d+)", re.IGNORECASE)

_STATUS_MARK = {"done": "✅", "partial": "🔶", "todo": "⬜"}


def _tier_for(path: Path) -> str:
    """Classify a test file by path: 'integration' if under an integration dir."""
    return "integration" if "integration" in path.parts else "unit"


@dataclass
class Requirement:
    spec: str  # "002"
    num: str  # "009"
    status: str  # done | partial | todo
    intended_tier: str = "integration"  # integration (default) | unit
    sr: str | None = None  # parent System Requirement, e.g. "SR-004"
    tests: list[tuple[str, str]] = field(default_factory=list)  # (path, tier)

    @property
    def fid(self) -> str:
        return f"{self.spec}:FR-{self.num}"

    @property
    def has_integration(self) -> bool:
        return any(tier == "integration" for _, tier in self.tests)

    @property
    def covered(self) -> bool:
        """True if the FR's intended-tier coverage requirement is met."""
        if not self.tests:
            return False
        return self.has_integration if self.intended_tier == "integration" else True


def parse_specs(specs_dir: Path) -> dict[str, Requirement]:
    """Collect every FR across all specs, keyed by "NNN:FR-MMM"."""
    reqs: dict[str, Requirement] = {}
    for spec_md in sorted(specs_dir.glob("[0-9][0-9][0-9]-*/spec.md")):
        spec_num = spec_md.parent.name[:3]
        for line in spec_md.read_text(encoding="utf-8").splitlines():
            m = _FR_LINE.search(line)
            if not m:
                continue
            sr = m.group("sr")
            r = Requirement(
                spec=spec_num,
                num=m.group("num"),
                status=m.group("status"),
                intended_tier=m.group("tier") or "integration",
                sr=f"SR-{int(sr):03d}" if sr else None,
            )
            reqs[r.fid] = r
    return reqs


def parse_srs(specs_dir: Path) -> dict[str, str]:
    """Read the System-Requirement catalog (id -> title) from requirements.md."""
    srs: dict[str, str] = {}
    path = specs_dir / "requirements.md"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _SR_HEADER.match(line)
            if m:
                srs[f"SR-{int(m.group('num')):03d}"] = m.group("title")
    return srs


def render_sr_rollup(reqs: dict[str, Requirement], srs: dict[str, str], *, markdown: bool) -> str:
    """SR -> FR -> test rollup: which foundation each FR serves, and the gaps."""
    by_sr: dict[str, list[Requirement]] = {}
    orphans: list[str] = []
    for r in reqs.values():
        if r.sr:
            by_sr.setdefault(r.sr, []).append(r)
        else:
            orphans.append(r.fid)

    lines: list[str] = []
    h = lines.append
    h("\n## System Requirements (SR) rollup\n" if markdown else "\nSystem Requirements (SR) rollup")
    if markdown:
        h("| SR | Title | FRs | done covered | FR ids |")
        h("|----|-------|-----|--------------|--------|")
    for sid in sorted(set(srs) | set(by_sr)):
        title = srs.get(sid, "(not declared in requirements.md)")
        frs = sorted(by_sr.get(sid, []), key=lambda r: (r.spec, int(r.num)))
        done = sum(1 for r in frs if r.status == "done")
        done_cov = sum(1 for r in frs if r.status == "done" and r.covered)
        flag = ""
        if sid not in srs:
            flag = "  <-- tagged on FRs but NOT declared in requirements.md"
        elif not frs:
            flag = "  <-- no FR traces here yet"
        if markdown:
            ids = ", ".join(r.fid for r in frs) or "—"
            h(f"| {sid} | {title} | {len(frs)} | {done_cov}/{done} | {ids} |")
        else:
            h(f"  {sid}  FRs={len(frs):<2} done-covered={done_cov}/{done}  {title}{flag}")
            for r in frs:
                h(f"            {_STATUS_MARK.get(r.status, '?')} {r.fid}")

    if orphans:
        h("")
        h("### FRs with no SR (orphans)" if markdown else "FRs with no SR (orphans):")
        for o in sorted(orphans):
            h(f"- {o}" if markdown else f"  {o}")
    return "\n".join(lines) + "\n"


def scan_tests(test_roots: list[Path]) -> dict[str, list[tuple[str, str]]]:
    """Map each referenced "NNN:FR-MMM" to the (test file, tier) refs."""
    refs: dict[str, list[tuple[str, str]]] = {}
    for root in test_roots:
        if not root.exists():
            continue
        for py in sorted(root.rglob("test_*.py")):
            text = py.read_text(encoding="utf-8")
            tier = _tier_for(py)
            for ref in _REQ_REF.finditer(text):
                for idm in _REQ_ID.finditer(ref.group("ids")):
                    fid = f"{idm.group('spec')}:FR-{idm.group('num')}"
                    refs.setdefault(fid, [])
                    entry = (str(py), tier)
                    if entry not in refs[fid]:
                        refs[fid].append(entry)
    return refs


def write_tag_manifests(
    core_tests: Path, ha_tests: Path, refs: dict[str, list[tuple[str, str]]]
) -> None:
    """Write per-repo committed manifests of the requirement tags found in tests."""
    repos = {
        "hemm": core_tests,
        "ha-hemm": ha_tests,
    }
    by_repo: dict[str, set[str]] = {repo: set() for repo in repos}
    for fid, entries in refs.items():
        for test_path, _tier in entries:
            path = Path(test_path).resolve()
            for repo, tests_dir in repos.items():
                try:
                    path.relative_to(tests_dir.resolve())
                except ValueError:
                    continue
                by_repo[repo].add(fid)

    for repo, tests_dir in repos.items():
        if not tests_dir.is_dir():
            continue
        manifest = {
            "schema_version": 1,
            "repo": repo,
            "frs": sorted(by_repo[repo]),
        }
        out = tests_dir / "req_tags_manifest.json"
        out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")


def build_matrix(
    reqs: dict[str, Requirement], refs: dict[str, list[tuple[str, str]]]
) -> list[str]:
    """Attach references to requirements; return unknown referenced ids."""
    unknown: list[str] = []
    for fid, entries in refs.items():
        if fid in reqs:
            reqs[fid].tests = entries
        else:
            unknown.append(fid)
    return sorted(unknown)


def render_report(reqs: dict[str, Requirement], unknown: list[str], *, markdown: bool) -> str:
    by_spec: dict[str, list[Requirement]] = {}
    for r in reqs.values():
        by_spec.setdefault(r.spec, []).append(r)

    def tier_label(r: Requirement) -> str:
        if not r.tests:
            return "no-test"
        if r.has_integration:
            return "integration"
        return "unit-only" if r.intended_tier == "integration" else "unit"

    lines: list[str] = []
    h = lines.append
    h("# Requirement Coverage\n" if markdown else "Requirement Coverage")
    for spec in sorted(by_spec):
        rows = sorted(by_spec[spec], key=lambda r: int(r.num))
        done = sum(1 for r in rows if r.status == "done")
        done_cov = sum(1 for r in rows if r.status == "done" and r.covered)
        h("")
        h(f"## Spec {spec}" if markdown else f"[{spec}]")
        h(f"done FRs covered at intended tier: {done_cov}/{done}")
        if markdown:
            h("")
            h("| FR | Status | Want | Coverage | Tests |")
            h("|----|--------|------|----------|-------|")
        for r in rows:
            mark = _STATUS_MARK.get(r.status, "?")
            tlabel = tier_label(r)
            gap = r.status == "done" and not r.covered
            flag = ""
            if gap and not r.tests:
                flag = "  <-- claimed done, NO TEST"
            elif gap:
                flag = "  <-- needs integration test"
            if markdown:
                tcell = ", ".join(Path(t).name for t, _ in r.tests) or "—"
                warn = " ⚠️" if gap else ""
                h(f"| FR-{r.num} | {mark} {r.status} | {r.intended_tier} | {tlabel}{warn} | {tcell} |")
            else:
                h(f"  FR-{r.num}  {mark} {r.status:<7} want={r.intended_tier:<11} [{tlabel}]{flag}")
    if unknown:
        h("")
        h("## Unknown references (test points at a missing FR)" if markdown else "Unknown references:")
        for u in unknown:
            h(f"- {u}" if markdown else f"  {u}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Requirement-coverage audit.")
    parser.add_argument("--specs", default="specs", help="Specs directory (default: specs)")
    parser.add_argument(
        "--tests",
        action="append",
        default=None,
        help="Test root to scan (repeatable). Default: core tests/ + sibling ha-hemm/tests",
    )
    parser.add_argument(
        "--ha-tests",
        default=None,
        help="ha-hemm tests dir (default: sibling ../ha-hemm/tests). Used for scanning and manifest writing.",
    )
    parser.add_argument("--markdown", metavar="PATH", help="Write a Markdown matrix to PATH")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any FR marked 'done' has no referencing test, or a test references an unknown FR.",
    )
    parser.add_argument(
        "--write-tag-manifests",
        action="store_true",
        help="Write per-child-repo req_tags_manifest.json files from the tags currently present in tests.",
    )
    args = parser.parse_args(argv)

    base = Path(args.specs).resolve().parent  # core repo root (parent of specs/)
    specs_dir = Path(args.specs).resolve()
    if not specs_dir.is_dir():
        print(f"error: specs dir not found: {specs_dir}", file=sys.stderr)
        return 1

    core_tests = base / "tests"
    ha_tests = (
        Path(args.ha_tests).resolve() if args.ha_tests else base.parent / "ha-hemm" / "tests"
    )

    test_roots = (
        [Path(t).resolve() for t in args.tests]
        if args.tests
        else [core_tests, ha_tests]
    )

    reqs = parse_specs(specs_dir)
    if not reqs:
        print(f"error: no FRs found under {specs_dir}", file=sys.stderr)
        return 1
    srs = parse_srs(specs_dir)
    refs = scan_tests(test_roots)
    unknown = build_matrix(reqs, refs)

    if args.write_tag_manifests:
        write_tag_manifests(core_tests, ha_tests, refs)

    print(render_report(reqs, unknown, markdown=False), end="")
    print(render_sr_rollup(reqs, srs, markdown=False), end="")

    if args.markdown:
        md = render_report(reqs, unknown, markdown=True) + render_sr_rollup(reqs, srs, markdown=True)
        Path(args.markdown).write_text(md, encoding="utf-8")
        print(f"\nwrote {args.markdown}")

    if args.check:
        no_test = sorted(r.fid for r in reqs.values() if r.status == "done" and not r.tests)
        unit_only = sorted(
            r.fid
            for r in reqs.values()
            if r.status == "done" and r.tests and not r.covered
        )
        undeclared_sr = sorted(
            {r.sr for r in reqs.values() if r.sr and r.sr not in srs}
        )
        failed = bool(no_test or unit_only or unknown or undeclared_sr)
        if no_test:
            print(f"\nFAIL: {len(no_test)} 'done' FRs without a test: {', '.join(no_test)}", file=sys.stderr)
        if unit_only:
            print(f"FAIL: {len(unit_only)} 'done' FRs need an integration test (unit-only): {', '.join(unit_only)}", file=sys.stderr)
        if unknown:
            print(f"FAIL: {len(unknown)} test refs to unknown FRs: {', '.join(unknown)}", file=sys.stderr)
        if undeclared_sr:
            print(f"FAIL: {len(undeclared_sr)} FRs tag an SR not declared in requirements.md: {', '.join(undeclared_sr)}", file=sys.stderr)
        return 1 if failed else 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
