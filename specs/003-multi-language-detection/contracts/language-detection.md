# Contract: Language Detection

**Satisfies**: FR-L-001–FR-L-011 | **Module**: `shared/tools/language.py` | **Consumer**: `orchestration/scheduler.py` (language-decision gate, FR-015–FR-020)

## Public functions

### `detect_language(html: str) -> str`

**Unchanged signature.** Preserved exactly as it exists today so the current call site (`orchestration/scheduler.py:259`, inside the `language_detection` trace span and `stage_log.timed` block) requires no change to keep working.

- **Input**: full page HTML as a string.
- **Output**: an ISO 639-1 language code (lowercase, no region/script subtag — e.g. `"de"`, `"ar"`, `"zh"`), a documented fallback code for a language with no 639-1 code, or the literal string `"unknown"`.
- **Guarantee**: never returns `"en"` unless English was positively identified — either via a well-formed declared attribute or as the winning text-analysis candidate (FR-L-003).
- **Guarantee**: never raises for malformed or unparseable HTML, or for detector-internal errors; returns `"unknown"` instead (Edge Cases table, spec.md).
- **Guarantee**: no network I/O, no LLM call, synchronous (FR-L-009).

### `detect_language_detailed(html: str) -> LanguageDetectionResult`

**New.** Same detection logic as `detect_language`; returns the full result including basis and confidence (FR-L-010). `detect_language` is implemented as `detect_language_detailed(html).language`.

- **Input**: same as above.
- **Output**: `LanguageDetectionResult` — see [data-model.md](../data-model.md) for field definitions and validation rules.

## Decision procedure (normative)

Given `html`:

1. Parse `html`. Locate the `<html>` tag's `lang` attribute.
2. **If present and well-formed** (FR-L-005, research R6): return `language=<primary subtag>`, `source="declared_attribute"`, `confidence=None`, `text_length=0`. Text analysis is **not** invoked.
3. **Otherwise**, extract visible text with boilerplate suppression (FR-L-006, research R5).
4. **If extracted text length < `language_detection_min_text_chars`** (FR-L-008, research R4): return `language="unknown"`, `source="undetermined"`, `confidence=None`, `text_length=<actual length>`. The classifier is **not** invoked.
5. **Otherwise**, run the classifier (research R1/R2) to get ranked, normalized-probability candidates.
6. **If the top candidate's probability < `language_detection_confidence_threshold`**, or **the top two candidates' probability gap < `language_detection_margin_threshold`** (FR-L-007, research R2/R3): return `language="unknown"`, `source="text_analysis"`, `confidence=<top candidate's probability>`, `text_length=<actual length>`.
7. **Otherwise**: return `language=<top candidate, normalized per FR-L-011>`, `source="text_analysis"`, `confidence=<top candidate's probability>`, `text_length=<actual length>`.

Step order is significant: declared-attribute check always precedes text analysis (FR-L-005), and the minimum-text check always precedes the classifier call (R4 — no point classifying text too short to trust).

## What this contract does NOT cover

- Whether a returned language is in `AIQ_SUPPORTED_LANGUAGES` — that comparison is `language_requires_decision()` in `orchestration/routers/language_decision.py`, unchanged by this feature (FR-L-013).
- What happens after a human decision is raised — unchanged (spec 001, FR-017–FR-020).
- Translating detected non-English content — out of scope (spec.md, Out of Scope).

## Failure mode

Any unexpected exception inside detection (parser failure, classifier error) MUST be caught at the top of `detect_language_detailed` and converted to the same `unknown`/`"undetermined"` result described in step 4, with the exception logged at `WARNING` level. Detection failure must never propagate to the caller as an exception (Edge Cases table, spec.md — "Detection raises an unexpected internal error").
