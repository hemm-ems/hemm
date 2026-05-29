# HEMM Specs — requirements & coverage

Spec-Driven Development for HEMM (via [Spec Kit](https://github.com/github/spec-kit)).
Specs live in the core repo (`hemm`), which is the home base, because features
are cross-cutting (`hemm` core + `ha-hemm` integration). Norms are in `AGENT.md`;
principles in `.specify/memory/constitution.md`.

## Layout

```
specs/
├── requirements.md   # the top of the V: ~11 System Requirements (SR), hand-authored
├── NNN-slug/
│   ├── spec.md       # WHAT + WHY: user stories, Functional Requirements, success criteria
│   ├── plan.md       # HOW: technical approach, structure, open work
│   └── tasks.md      # the work breakdown ([X] built, [ ] open)
└── coverage.md       # generated traceability matrix (do not hand-edit)
```

## Requirement hierarchy: SR → FR → test

`requirements.md` holds the foundational **System Requirements** (`SR-NNN`) — what
HEMM *is* and the mechanisms it's built on. It is the one requirements file a human
edits; SRs carry no hand-typed status. Each `FR-NNN` declares its parent SR with a
`` `SR-NNN` `` tag, placed as the **last backtick token before the colon** (after the
tier token if present), so the tier parser ignores it:

```text
- **FR-001** `✅ done` `SR-006`: ...          # integration FR, parent SR-006
- **FR-006** `✅ done` `unit` `SR-006`: ...    # unit FR, parent SR-006
```

The coverage tool rolls this up (SR → FR → test) and flags both directions: an SR with
no FR tracing to it (an unspecced foundation) and an FR tagging an SR absent from
`requirements.md` (the latter fails `--check`).

## Requirement status (in spec.md)

Each FR carries a status tag:

- `✅ done` — implemented **and** must be backed by a referencing test.
- `🔶 partial` — partially implemented (e.g. a stub, or a correctness gap).
- `⬜ todo` — not yet built; drives a live task in `tasks.md`.

`done` is a claim, not a fact, until a test points at it — see the coverage tool.

### Test tier (in spec.md)

A `done` FR also declares the *tier* its test must reach, written as a second
backtick token right after the status:

- (no tag) → **integration** (default): must be proven by a test that runs against
  a real Home Assistant container (`ha-hemm/tests/integration/`). This is the bar
  for anything observable end-to-end through HA — config flow, manifests,
  constraints, entities, services, and a real `replan`/`tick`/`simulate` solve.
- `` `unit` `` → the FR is genuinely pure logic that HA cannot observe (solver
  math like power bounds / SoC / COP, JSON-Schema export, message *definitions*,
  the CLI sim harness, library ABCs). A unit test alone satisfies it.

```text
- **FR-007** `✅ done`: ...           # integration (default) — needs a Docker test
- **FR-003** `✅ done` `unit`: ...    # pure solver math — a unit test is enough
```

Pick `unit` only when an HA-level test would be indirect or fragile, never to dodge
writing a real integration test. The default is integration on purpose.

## Linking tests to requirements

Tag a test with the FR(s) it exercises. Format: `NNN:FR-MMM` where `NNN` is the
spec directory number (stable across renames).

```python
@pytest.mark.req("001:FR-002")
def test_missing_safe_default_raises(): ...

@pytest.mark.req("002:FR-010", "002:FR-011")
def test_per_device_penalty(): ...
```

Equivalent zero-config comment form (no marker registration needed):

```python
# REQ: 001:FR-002
```

The `req` marker is registered in each repo's `pyproject.toml` so it works under
`--strict-markers` and is queryable: `pytest -m req`.

## Coverage tool

`tools/req_coverage.py` (pure stdlib, runs from the parent) parses every
`spec.md`, scans `hemm/tests` and `ha-hemm/tests` for `req` references, and
builds the matrix. It makes FR status *derived*, not asserted.

```bash
python3 tools/req_coverage.py                       # print matrix
python3 tools/req_coverage.py --markdown specs/coverage.md   # write matrix
python3 tools/req_coverage.py --check               # exit 1 if a 'done' FR has no test
```

`--check` is the gate. A `✅ done` FR fails it when:

- it has **zero** referencing tests, or
- its tier is integration (the default) but only **unit** tests reference it
  (shown as `[unit-only]  <-- needs integration test`), or
- a test references a non-existent FR.

So "covered" means *proven end-to-end in Docker* by default — a shallow unit test
no longer silences the gate for an integration-tier FR. The report prints the tier
that actually covers each FR (`[integration]`, `[unit]`, `[unit-only]`, `[no-test]`).
`--check` is wired into the core repo's Traceability workflow, which checks out
`ha-hemm` as a sibling so the gate sees both repos' tests. Run it locally with
`make gate` from the core repo (needs `../ha-hemm` checked out).

Test tier is derived from the test's path: anything under an `integration/`
directory is an integration test; everything else is a unit test.

## Working order

1. Back-tag existing tests to their `✅ done` FRs → coverage turns honest.
2. Fix correctness gaps first (e.g. `002:FR-009` thermal no-op, `001:FR-013`
   verify-entity guard), each landing with a `req`-tagged test.
3. Then feature FRs (`⬜`), spec-driven via `/speckit-*`.
