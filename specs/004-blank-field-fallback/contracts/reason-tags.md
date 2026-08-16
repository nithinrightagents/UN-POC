# Contract: Reason Tag lookup

**Module**: `shared/state/reason_tags.py` (new)
**Consumers**: `review/query.py` (review screen), `export/writer.py` (exclusion report `reason_tag` field)

## Function contract

```
def reason_tag(escalation_reason: str, context: dict) -> ReasonTag
```

- **Input**: `escalation_reason` — the raw string value already stored on every blocked unit (`unit["escalation_reason"]`, one of `EscalationReason`'s values). `context` — the same unit's stored `data` dict (already contains whatever the triggering condition recorded: `resolution_history`, `reported_languages`/`detected_language`, `validated_run_count`, etc.), plus, for the two language conditions, the associated `LanguageDecision` record's `detected_language` and `resolution_manner` when available.
- **Output**: `ReasonTag(text: str, condition: EscalationReason)` — see [data-model.md](../data-model.md) for the field shapes and the full template table.
- **MUST NOT** return `None`, raise, or fall back to a generic label for any `EscalationReason` member — every member has a table entry (FR-BF-001, FR-BF-006). A member added to `EscalationReason` in the future without a corresponding template entry is a programming error this function's exhaustiveness test catches at test time, not a runtime `KeyError` a reviewer would hit live.
- **MUST** always return the same `text` for the same `escalation_reason` + equivalent `context` values — no randomness, no model call, no time-of-day dependence (FR-BF-006's determinism requirement).
- **Language-decision sub-case**: when `escalation_reason == "language_declined"`, the function additionally inspects `resolution_manner` (`"explicit"` vs `"window_expired"`) to select between the "reviewer declined" wording and the "window expired" wording (FR-BF-006's edge case). This is the one condition with two templates instead of one; both are still fixed and canonical, selected deterministically by `resolution_manner`, never freely composed.

## What this contract deliberately does NOT cover

- Where the reason tag is *displayed* (that's `review/web/templates/question.html` and `questions.html`, and `export/writer.py`'s exclusion-report assembly — this module only produces the value).
- The exact final English wording — the template table in data-model.md is normative for *shape and determinism*; minor copy wording may be refined during implementation as long as every template still begins `"Left blank: "` and still names its specific condition (FR-BF-005, FR-BF-006).
