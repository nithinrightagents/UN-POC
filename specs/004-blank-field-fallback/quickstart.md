# Quickstart: Prefilled Questionnaire Blank-Field Fallback

**Feature Directory**: `specs/004-blank-field-fallback`
**Spec**: [spec.md](./spec.md)

Validation scenarios below map 1:1 to the spec's User Scenarios. All run against the existing `pytest` setup (`testpaths = ["tests"]`, `asyncio_mode = "auto"`, per `pyproject.toml`) plus one manual web-app smoke check. No new dependency, no new database, no new CLI command is required beyond one seed-data extension (Scenario 0).

## Prerequisites

```bash
uv sync --extra dev   # or: pip install -e ".[dev]"
```

An existing `.env` (or defaults) is sufficient — this feature adds no new configuration.

## Scenario 0 — Seed data for every blocking condition

`review/seed_demo.py` today seeds one complete assessment and one with broken evidence (`aiq seed demo-review`). This feature needs a unit in each of the six blocking conditions to demo/test against. Extend the seed (or add fixtures under `tests/fixtures/blank_field/`) with one unit per `EscalationReason` member, each carrying a realistic `context` (a short `resolution_history`, an `AssessorAgentRun` or two where applicable, etc.) so every downstream scenario has real data to point at.

```bash
aiq seed demo-review   # after extension, seeds blocked-condition units too
```

**Expected**: seven or eight units exist across one or two demo portals — one `DELIVERED`, one for each `EscalationReason` value (`UNASSESSABLE` for `NO_USABLE_URL`, `ESCALATED` for the rest).

## Scenario 1 — Blank field, not a forced guess or a blocked screen (User Story 1)

```bash
pytest tests/unit/test_blank_field_fallback.py -k coverage -v
```

**Expected**: for every seeded blocking condition, `build_question_review()` returns `escalated=True`, `delivered_answer=None`, and a non-empty `reason_tag`. No test asserts a non-`None` `delivered_answer` for any of these units before a human decision exists.

Manual check:

```bash
aiq serve
# open http://<host>:<port>/portal/<demo-portal>/question/<demo-question>?session=<demo-session>
```

**Expected**: the question shows a blank "Proposed answer" (never the literal text `None`) and a "Left blank: ..." reason line; the portal's question list shows every blocked question, including the `UNASSESSABLE` one, marked as blocked; every other question on the same portal remains independently approvable/editable.

## Scenario 2 — Evidence and attempt history on screen (User Story 2)

```bash
pytest tests/unit/test_blank_field_fallback.py -k attempt_history -v
```

**Expected**: `attempt_history` on the review view carries the resolution attempts, retry counts, and (for the disagreement unit) every round's agent positions and points of disagreement — asserted directly against the seeded fixture data, no manual log inspection required to write the test.

Manual check: open the disagreement unit's review screen; expand the attempt-history disclosure; confirm every round's agent answers/confidence/justification are visible, and that the `NO_USABLE_URL` unit's screen states explicitly that no evidence exists rather than rendering an empty section.

## Scenario 3 — Reason tags are canonical and exhaustive (User Story 3)

```bash
pytest tests/unit/test_reason_tags.py -v
```

**Expected**: a parametrized test iterates every `EscalationReason` member and asserts `reason_tag()` returns a distinct, deterministic `"Left blank: ..."` string for each (calling it twice with the same inputs returns identical text); the two `LANGUAGE_DECLINED` sub-cases (explicit vs. window-expired) are asserted to differ.

## Scenario 4 — A reviewer's answer to a blank field reaches export (FR-BF-013–015, SC-005)

```bash
pytest tests/unit/test_phase9_export.py -k blocked -v
```

**Expected**: after posting an `edit` decision for a blocked unit (via `review/actions.py::edit`, the same path the `/edit` web endpoint uses), `export_cycle_answers()` includes that question in the delivered NDJSON — not the exclusion report — with `provenance: "human_edited"`. A blocked unit with no decision yet still appears only in the exclusion report, now carrying both `reason` (unchanged code) and the new `reason_tag`.

## Scenario 5 — Export invariant gap closed

```bash
pytest tests/unit/test_phase9_export.py -k language_not_supported -v
```

**Expected**: a cycle containing a `LANGUAGE_NOT_SUPPORTED`-escalated unit exports without raising `ExportInvariantError` — this reproduces and then closes the latent gap identified in research.md R5.

## Scenario 6 — Regression: existing suite still passes unmodified

```bash
pytest tests/unit tests/contract tests/integration -q
```

**Expected**: full pass. In particular, `tests/unit/domain/test_unit_state.py`'s `assert_exhaustive_terminal_coverage` check continues to pass unchanged — this feature never modifies `unit_state.py`'s transition table (research R3).
