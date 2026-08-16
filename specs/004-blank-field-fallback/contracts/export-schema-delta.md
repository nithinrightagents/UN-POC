# Contract: Answer export delta

Extends spec 001's [export-schema.md](../../001-ekap-aiq-assessment/contracts/export-schema.md) (FR-101–FR-106). This document states only what changes; every invariant (E1–E7) and every existing field not listed here is unchanged.

## Exclusion report item — additive field

**Before** (today, `export/writer.py`):

```json
{"country_id": "...", "question_id": "...", "reason": "requires_authenticated_access"}
```

**After**:

```json
{"country_id": "...", "question_id": "...", "reason": "requires_authenticated_access", "reason_tag": "Left blank: Login authentication barrier observed"}
```

- `reason` — **unchanged**, same machine-readable code, same values, same consumers unaffected (FR-BF-015: "without changing or removing the existing code").
- `reason_tag` — **new**, always present when `reason` corresponds to a blocking condition covered by [contracts/reason-tags.md](./reason-tags.md); the same string a reviewer sees on the question's review screen for that unit.
- A unit still excluded for a non-blocking reason (`"awaiting_human_review"` — a question that simply hasn't been reviewed yet, not a blocked one) does **not** get a `reason_tag`; there is no blocking condition to name. `reason_tag` is only ever populated alongside a `reason` value that is one of `EscalationReason`'s values.

## `VALID_EXCLUSION_REASONS` — one addition, one structural change

- Adds `"language_not_supported"` (closes the latent gap in research.md R5 — this value is already reachable today and export would already fail on it).
- Going forward, this set is asserted (by test, not by runtime code) to equal `{r.value for r in EscalationReason}` rather than being maintained as an independent literal, so a future new `EscalationReason` member cannot silently reintroduce the same class of gap.

## Delivered-record inclusion — one additional eligibility path

No change to the delivered NDJSON record's **shape** (every field in FR-102 is unchanged). The **eligibility rule** for which units produce a delivered record gains a second path, per [data-model.md](../data-model.md)'s "Modified: export inclusion rule":

1. `unit.state == DELIVERED` (existing, unchanged), or
2. `unit.state` is blocked and the unit has a recorded human decision.

A record produced via path 2 sets `provenance` to `"human_edited"` or `"human_overridden"` — never `"system_proposed"` — since a blocked unit has no system-proposed answer to have approved (FR-BF-002). Its `evidence_refs` reflects whatever partial evidence existed before the block (possibly empty, per FR-BF-010) rather than a full assessment's evidence.

## Explicitly unchanged

- Export invariants E1 ("only delivered answers"), E2 (benchmark exclusion), E3 (session_id + evidence_refs required) — a path-2 record satisfies all three exactly as a path-1 record does; `delivered_answer: true` still means what it always meant.
- The NDJSON file format, the exclusion-report file's top-level shape (`{"cycle_id": ..., "excluded": [...]}`), and the `AnswerExport` audit record (FR-106) — none of these change.
