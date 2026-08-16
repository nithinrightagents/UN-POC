# Data Model: Multi-Language Detection for Portal Pages

**Feature Directory**: `specs/003-multi-language-detection`
**Spec**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

This feature adds one new value type and extends none of the persisted entities from spec 001. It does not touch the database schema — `LanguageDecision` (spec 001) is consumed unchanged (FR-L-013).

---

## `LanguageDetectionResult`

The return type of `detect_language_detailed()` (research R7). Not persisted as its own table; its fields are surfaced through the existing `language_detection` trace span and stage event (FR-L-010) as metadata on those existing records, not a new entity with its own identity or lifecycle.

| Field | Type | Description | Set by |
|---|---|---|---|
| `language` | `str` | ISO 639-1 code (lowercase, e.g. `"de"`), a documented fallback form for languages with no 639-1 code (FR-L-011), or the sentinel `"unknown"` | Always |
| `source` | `"declared_attribute" \| "text_analysis" \| "undetermined"` | Which signal produced `language`. `"undetermined"` when `language == "unknown"` and no text analysis was even attempted (e.g. below the FR-L-008 minimum-text floor) | Always |
| `confidence` | `float \| None` | Normalized probability of the winning candidate (research R2), in `[0, 1]`. `None` when `source` is `"declared_attribute"` (the attribute carries no probabilistic confidence) or `"undetermined"` | When `source == "text_analysis"` |
| `text_length` | `int` | Character count of the boilerplate-stripped visible text the decision was based on. `0` when `source == "declared_attribute"` (text analysis was not invoked, per FR-L-005) | Always |

### Validation rules

- `language` is always lowercase and has no region/script subtag (FR-L-011) — `"en-GB"` never appears as a value, only `"en"`.
- `confidence`, when present, is in `[0.0, 1.0]`.
- `source == "declared_attribute"` ⟹ `confidence is None` and `text_length == 0`.
- `language == "unknown"` ⟹ `confidence is None or confidence < <configured threshold>` (an `unknown` result is never paired with a confidence value that would have cleared the threshold — that would be a contradiction between the two fields).
- `language != "unknown"` ⟹ `source in {"declared_attribute", "text_analysis"}` (never `"undetermined"` for a positively identified language).

### Relationships

`LanguageDetectionResult` is consumed at exactly one point: the language-decision gate in `orchestration/scheduler.py`. It is:

1. Reduced to its `language` field for the existing `language_requires_decision(detected_language, supported_languages)` check (`orchestration/routers/language_decision.py` — unchanged, FR-L-013).
2. Attached in full to the `language_detection` LangSmith span (`lang_span.patch(outputs={...})`, FR-T-002) and to the `stage_log.timed("language_detection", unit_ref, ...)` stage event (FR-113/FR-114), so `source`, `confidence`, and `text_length` are queryable telemetry (SC-007) without changing either telemetry system's schema. `safe_trace`'s `outputs` parameter is already free-form. `StageEventLog` has no generic kwargs channel for custom fields (`record()` only accepts `agent_index`/`round_number` beyond the fixed `StageEvent` fields) — but `unit_ref` is itself an arbitrary dict stored verbatim on the event, so the three fields are added there: the call site builds `unit_ref` as a local variable, passes it into `timed()`, and mutates it with the detection detail after `detect_language_detailed()` returns but before the `with` block exits (the same dict object is read when `record()` fires in `timed()`'s `finally` clause).
3. **Not stored** anywhere else. It does not become a new field on `LanguageDecision`, `UnitState`, or any persisted table. If a human later needs to know *why* a page was classified as `unknown`, they consult the trace span or stage event for that unit, not a new database column.

---

## Configuration additions

Three new settings, following the existing pattern in `shared/config/settings.py` (`AIQ_*` env vars, typed fields on `Settings`, defaults documented in `contracts/configuration.md`). See [contracts/configuration.md](./contracts/configuration.md) for the full parameter table with defaults and validation.

| Setting | Purpose | Backing research |
|---|---|---|
| `language_detection_confidence_threshold` | FR-L-007's minimum confidence floor | R2 |
| `language_detection_margin_threshold` | FR-L-007's top-2 ambiguity margin | R3 |
| `language_detection_min_text_chars` | FR-L-008's minimum-text floor | R4 |

None of these are new persisted entities — they are configuration values read into the existing `Settings` dataclass and captured by the existing Configuration Snapshot mechanism (spec 001, FR-075), which already applies to every field on `Settings` without per-field wiring.

---

## Fixture corpus (test data, not runtime data)

Not an application entity — recorded here because FR-L-012 requires it and it has a defined shape.

| Field | Description |
|---|---|
| File | Saved HTML snapshot of a real government portal page (research R8) |
| Expected language | The ground-truth ISO 639-1 code the fixture is labeled with (or `"unknown"` for the deliberately-ambiguous cases), used as the test assertion target |
| Case tag | Which FR-L-012 requirement the fixture demonstrates (e.g. `"untagged-de"`, `"boilerplate-en-over-nl"`, `"malformed-lang-attr"`, `"too-short"`, `"bilingual-fr-en"`, `"out-of-set-tr"`) |

Lives under `tests/fixtures/language_detection/`, mirroring the existing static-fixture convention in `tests/fixtures/resolution/` and `tests/fixtures/adjudication/`.

---

## No changes to existing entities

For completeness, explicitly confirmed unchanged (FR-L-013):

- `LanguageDecision` (spec 001 `shared/state/entities.py`) — same fields, same lifecycle (pending → authorized / declined / expired). It receives a `detected_language` value that is now *correct* more often, but the field itself and everything that reads it is untouched.
- `Settings.supported_languages`, `Settings.language_decision_window_hours` — untouched.
- Any database schema/table — no migration required.
