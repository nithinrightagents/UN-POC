# Feature Specification: Multi-Language Detection for Portal Pages

**Feature**: `003-multi-language-detection`
**Status**: Superseded — see notice below
**Created**: 2026-08-14

> **Superseded 2026-08-14.** Everything below describes the originally
> planned design: a standalone `py3langid`-based detector feeding the
> existing FR-015–FR-020 human decision gate. After this spec was fully
> implemented, the user rejected that architecture directly ("I dont want a
> python package detecting the lang ... the LLM should see if it's in the
> allowed lang list else it should raise error") and confirmed, via two
> follow-up clarifying questions, that the human decision gate should be
> **removed entirely** and replaced with a **hard error** when the assessor
> LLM's own inline language report is outside `AIQ_SUPPORTED_LANGUAGES`.
>
> The implementation now in the codebase reflects that later decision, not
> this document:
> - `src/agents/assessor/agent.py` (`_RESPONSE_SCHEMA`) — each assessor LLM
>   call reports `detected_language` as part of its normal structured
>   response; no separate detection call, no detection package.
> - `src/shared/prompts/profiles.py` (`build_prompt`) — instructs the LLM to
>   report the language it observes, honestly, without influencing its
>   answer.
> - `src/orchestration/scheduler.py` (`process_unit`) — after assessment,
>   compares the majority reported language across independent agents
>   against `settings.supported_languages` and, if unsupported, escalates
>   via `EscalationReason.LANGUAGE_NOT_SUPPORTED` (a hard stop, not a
>   pending human decision).
> - The `py3langid` dependency, the `shared/tools/language.py` detector, its
>   three `AIQ_LANGUAGE_DETECTION_*` settings, and its fixture corpus have
>   all been removed.
> - The FR-015–FR-020 pending/authorized/declined/expired decision flow
>   (`orchestration/routers/language_decision.py`, the `LanguageDecision`
>   entity) is no longer invoked from the scheduler; its code and DB table
>   are left in place only because `review/audit.py` still reads historical
>   records for old sessions, not because any new decision flow exists.
>
> This spec file is kept for historical record. Tests: see
> `tests/unit/test_language_support_check.py`.

---

## Overview

The AIQ pipeline routes any portal page whose detected language falls outside the configured supported set to a human language-decision workflow (FR-015–FR-020). That gate is only as trustworthy as the detector feeding it.

`AIQ_SUPPORTED_LANGUAGES` is now configured with 13 languages: English, Spanish, French, German, Portuguese, Italian, Dutch, Russian, Chinese, Japanese, Korean, Arabic, Hindi. The detector behind the gate recognises far fewer. It reads the page's declared language attribute first — a good signal when present — but government portals frequently omit it, declare it wrongly, or declare a site-wide default that does not match the served page. When the detector falls back to page text, it can only distinguish English, French, Spanish and Portuguese (by a ten-word stopword list per language) and Chinese (by a character-count threshold).

The consequence is a silent correctness failure at the gate:

- An untagged page in **German, Italian, or Dutch** is classified as English, because unrecognised Latin-script text falls through to an unconditional English default. The page is treated as supported and assessed with no human ever seeing it — and if English were *not* in the supported set, it would be gated for the wrong language.
- An untagged page in **Russian, Japanese, Korean, Arabic, or Hindi** yields no Latin words at all and is classified as unknown, which does route to the human gate — but tells the human nothing about what language the page is actually in, and misattributes a supported language as undetectable.
- Any page in a language **outside** the supported set — the case the gate exists for — is subject to the same English default. This is the highest-impact failure: an unsupported-language portal is assessed as if it were English, producing answers from content no configured model was evaluated against, with full confidence and no best-effort marking (FR-018) and no human authorisation (FR-017).

This feature replaces the text-based detection path so that the language of a portal page is determined accurately from its content across all configured languages **and** across languages outside the configured set, with an honest "undetermined" result when the evidence is insufficient — never a silent default to English.

Detection only. Translating page content for a best-effort assessment (FR-018) is a separate, already-specified path and is unchanged by this feature.

---

## Clarifications

### Session 2026-08-14

- Q: Which mechanism should replace/extend the current text-based detector to cover all configured languages plus out-of-set detection? → A: A pure-Python statistical language-ID library with a bundled model and no compiled extension (e.g. `py3langid`) — no network calls, no C-extension build complexity, broad language coverage out of the box (Option A).
- Q: Should the human language-decision gate (FR-017 in spec 001-ekap-aiq-assessment) be kept as-is, or replaced with the assessor LLM deciding on its own whether it can handle a language? → A: Keep the existing human gate unchanged; this feature only makes the language *detection* feeding that gate accurate. FR-017's "never silently attempt" rule is unaffected.
- Q: Where should the FR-L-012 fixture corpus of test pages come from? → A: Real captured snapshots of actual government portal pages, across the 13 configured languages plus at least three languages outside the configured set (Option A).

---

## Actors

- **The pipeline** — calls detection once per unit, immediately after the first successful page fetch and before any assessor agent runs. It is the only caller; it consumes the result to decide whether the language-decision gate applies.
- **Reviewer / language-decision approver** — sees the detected language name in the pending language decision and decides whether to authorise a best-effort attempt, decline, or let the window expire (FR-017–FR-019). A wrong or absent detection makes that decision impossible to take responsibly.
- **Pipeline operator** — configures `AIQ_SUPPORTED_LANGUAGES`, and needs the set to mean what it says: every code listed must be one the detector can actually produce from page content.

---

## Functional Requirements

### FR-L-001: Detection covers every configured language, dynamically

The detector MUST be able to return any language code present in `AIQ_SUPPORTED_LANGUAGES` on the basis of page text alone, without the declared language attribute. Coverage MUST NOT be hard-wired to the current 13-code list: adding a code to `AIQ_SUPPORTED_LANGUAGES` MUST NOT require a change to the detector for that language to become detectable.

At minimum, the following MUST be detectable from text: English, Spanish, French, German, Portuguese, Italian, Dutch, Russian, Chinese, Japanese, Korean, Arabic, Hindi.

### FR-L-002: Unsupported languages are identified, not collapsed

The detector MUST identify languages **outside** the configured supported set as specifically as it identifies those inside it. A page in, for example, Turkish, Polish, Swahili or Thai MUST return that language's code — not English, not the nearest supported language, and not "unknown" merely because the code is absent from `AIQ_SUPPORTED_LANGUAGES`.

Filtering against the supported set is the responsibility of the language-decision gate, not the detector. The detector reports what the page is; the gate decides what that means.

### FR-L-003: No silent default to English

The detector MUST NOT return `en` as a fallback for text it could not classify. The current behaviour — returning `en` for any Latin-script page with no stopword match — MUST be removed. English MUST be returned only when it is positively identified.

### FR-L-004: Explicit undetermined result

When the detector cannot classify the page text with sufficient confidence, it MUST return the explicit sentinel `unknown`.

`unknown` MUST route the unit to the same human language-decision gate as an unsupported language (the existing `language_requires_decision` treatment of `unknown` is correct and MUST be preserved). The decision presented to the human MUST make clear that the language could not be determined, as distinct from a determined language that is unsupported.

The detector MUST return `unknown` in at least these cases:
- Page text contains too few usable characters to classify (see FR-L-008)
- Competing language candidates are too close to separate confidently (see FR-L-007)
- No candidate reaches the minimum confidence threshold

### FR-L-005: Declared language attribute remains the first signal

When the page's `<html lang>` attribute is present and well-formed, it MUST be used as the detection result without invoking text-based detection.

"Well-formed" means: a non-empty value whose primary subtag is a recognised two- or three-letter language code (region and script subtags such as `en-GB`, `zh-Hans-CN` are accepted and reduced to the primary subtag). Values that are empty, whitespace-only, not a recognised code, or placeholder values MUST be treated as absent, and detection MUST fall through to text-based analysis.

Text-based detection is the fallback path only. This feature does not change the precedence.

### FR-L-006: Detection runs on meaningful page content, not raw markup

Text-based detection MUST operate on the page's visible text with markup, scripts, and styles removed.

Because government portal pages routinely carry English navigation, footer, and cookie-banner boilerplate on otherwise non-English pages, detection MUST be biased toward the page's main content rather than toward whichever language appears in the most page chrome. Detection MUST NOT be decided by boilerplate when the main content is in a different language.

### FR-L-007: Confidence threshold and ambiguity handling

The detector MUST produce a confidence measure for its chosen candidate and MUST apply a configurable minimum confidence threshold below which the result is `unknown` (FR-L-004).

When the two highest-scoring candidates are within a configurable margin of each other, the result MUST be `unknown` rather than an arbitrary pick between them. This is the expected behaviour for genuinely bilingual portal pages.

### FR-L-008: Minimum text requirement

The detector MUST define a minimum quantity of extracted visible text below which it returns `unknown` rather than guessing. Short pages — error pages, redirect stubs, near-empty landing pages — MUST NOT be classified from a handful of words.

### FR-L-009: Detection stays on the hot path budget

Detection is invoked once per unit, synchronously, between the first page fetch and the assessor run. It MUST remain fast and self-contained:

- MUST NOT issue any network request
- MUST NOT issue any model/LLM call
- MUST NOT require a per-call download of model data or language resources; any required resource MUST be loaded once per process and reused
- MUST remain a synchronous, in-process call — the existing call shape at the call site is preserved
- MUST add no more than a small, bounded amount of time per unit relative to the page fetch it follows (see Success Criteria SC-005)

### FR-L-010: Detection result records its basis

Alongside the language code, the detection outcome MUST record:
- the signal that produced it — declared attribute vs. text analysis
- the confidence value, when the result came from text analysis
- the amount of text the decision was based on

This information MUST be available to the pipeline's telemetry and to the tracing span already wrapping this call (FR-T-002, `language_detection`), so that a disputed classification can be diagnosed after the fact without re-fetching the page.

The primary detection call MUST remain usable by the existing call site without the caller being required to consume the additional detail.

### FR-L-011: Language codes are consistent and comparable

Detection MUST return codes in the same form used by `AIQ_SUPPORTED_LANGUAGES` — lowercase ISO 639-1 two-letter codes where one exists — so that set membership comparison in the gate is exact. Codes MUST be normalised (case, region/script subtags stripped) before comparison. Where a detected language has no ISO 639-1 code, a documented fallback code form MUST be used consistently.

Chinese MUST be reported as `zh` regardless of script variant. Detection MUST NOT distinguish Simplified from Traditional in the returned code, since the configured set does not.

### FR-L-012: Behaviour is verifiable against a fixture corpus

The feature MUST ship with a fixture corpus of **real, captured snapshots of actual government portal pages** (saved HTML, not synthetically written) covering, at minimum:
- each of the 13 configured languages, without a declared language attribute
- at least three languages outside the configured set
- a page with English boilerplate around non-English main content
- a page with a wrong declared language attribute
- a page with a malformed or empty declared language attribute
- a page too short to classify
- a bilingual page with genuinely mixed content

Accuracy claims in Success Criteria are measured against this corpus.

### FR-L-013: Existing gate behaviour is preserved

This feature changes detection only. The language-decision gate, the pending-decision lifecycle, the response window, the best-effort authorisation path and its confidence cap (FR-015–FR-020) MUST be unchanged in behaviour. Every existing test covering the gate MUST pass unmodified.

---

## Deferred Design Decisions

The following remain open for `/speckit-plan` research. They are implementation-mechanism decisions; every requirement above is stated independently of how they resolve.

1. **Confidence and margin threshold values**: FR-L-007 requires the thresholds exist and be configurable; their default values should be set from measured behaviour on the FR-L-012 corpus, not guessed.
2. **Main-content extraction strategy** for FR-L-006 — whether boilerplate suppression is done by element-based content extraction, by weighting longer text blocks, or by another means.

Resolved: the detection mechanism (see Clarifications) is a pure-Python statistical language-ID library with a bundled model and no compiled extension.

---

## User Scenarios and Testing

### Scenario 1: Untagged German portal page (the core bug)

**Given** a portal page written in German with no `<html lang>` attribute
**When** the pipeline runs the language-decision gate for a unit on that portal
**Then** the detected language is `de`, and — because `de` is in `AIQ_SUPPORTED_LANGUAGES` — the unit proceeds directly to assessment with no human decision raised
**And** the unit is not recorded as English.

### Scenario 2: Untagged page in an unsupported language

**Given** a portal page written in Turkish with no `<html lang>` attribute, and `tr` absent from `AIQ_SUPPORTED_LANGUAGES`
**When** the language-decision gate runs
**Then** the detected language is `tr`
**And** a pending language decision is raised naming Turkish as the detected language
**And** the unit remains resumable and does not block other units in the batch (FR-020)
**And** the page is not assessed as English.

### Scenario 3: Untagged Arabic page

**Given** a portal page written in Arabic with no declared language attribute
**When** the gate runs
**Then** the detected language is `ar` (not `unknown`), and because `ar` is supported, assessment proceeds without a human decision.

### Scenario 4: English boilerplate around non-English content

**Given** a Dutch portal page whose navigation bar, cookie banner and footer are in English while the main content is Dutch, with no declared language attribute
**When** the gate runs
**Then** the detected language is `nl`.

### Scenario 5: Genuinely undetectable page

**Given** a portal page whose extracted visible text is a dozen words of ambiguous content
**When** the gate runs
**Then** the detected language is `unknown`
**And** a pending language decision is raised that states the language could not be determined
**And** the unit is not assessed as English.

### Scenario 6: Declared attribute wins when trustworthy

**Given** a portal page with `<html lang="ko">` and Korean content
**When** the gate runs
**Then** the detected language is `ko`, obtained from the declared attribute, and text-based detection is not invoked.

### Scenario 7: Malformed declared attribute falls through

**Given** a portal page with `<html lang="">` or `<html lang="default">` and Italian content
**When** the gate runs
**Then** the malformed attribute is disregarded and text-based detection returns `it`.

### Scenario 8: Bilingual page

**Given** a portal page with roughly equal French and English main content and no declared attribute
**When** the gate runs
**Then** the detected language is `unknown` rather than an arbitrary pick, and the unit routes to the human decision gate.

### Scenario 9: Hot path is undisturbed

**Given** any unit reaching the language-decision gate
**When** detection runs
**Then** no network request and no model call is made during detection
**And** the added time per unit is negligible relative to the page fetch that preceded it.

### Scenario 10: Regression safety

**Given** the existing suite of gate, router, and scheduler tests
**When** the new detector is in place
**Then** all of them pass without modification (FR-L-013).

---

## Edge Cases

| Case | Required behaviour |
|---|---|
| Page fetch failed / page unreachable | Detection is not invoked at all; existing unreachable handling applies. Unchanged. |
| `<html lang>` present but contradicts obvious page content | Declared attribute wins (FR-L-005). Text detection is not consulted. Cross-checking declared against detected is out of scope for this feature. |
| `<html lang="en-GB">`, `<html lang="zh-Hans-CN">` | Reduced to `en`, `zh`. |
| `<html lang>` with an unrecognised primary subtag (`xx`, `und`, `default`) | Treated as absent; text detection runs. |
| Page is entirely images / no extractable text | `unknown` (FR-L-008). |
| Page text is a language with no ISO 639-1 code | Documented fallback code form (FR-L-011); still routed by the gate as unsupported. |
| Latin-script language outside coverage of any chosen mechanism | `unknown`, never `en` (FR-L-003). |
| Serbian / Kazakh / other languages written in more than one script | Whatever the mechanism reports, normalised per FR-L-011; no special handling required. |
| Detection raises an unexpected internal error | Result is `unknown`, a warning is logged, and the unit routes to the human gate. Detection failure MUST NOT abort the unit or the batch. |
| Very large page (megabytes of text) | Detection operates on a bounded prefix/sample of extracted text to satisfy FR-L-009. |

---

## Key Entities

| Entity | Description | Change |
|---|---|---|
| Detection result | The language code returned for a page, plus its basis (declared vs. text), confidence, and text volume | Extended — code alone today |
| `unknown` sentinel | Explicit "could not determine" language value | Meaning preserved; frequency and correctness change |
| `AIQ_SUPPORTED_LANGUAGES` | Configured set of language codes the automated workflow may proceed on unaided | Unchanged in form; becomes truthful in effect |
| `LanguageDecision` record | The pending/authorized/declined/expired human decision, carrying `detected_language` | Unchanged in shape; now receives accurate codes |
| Fixture corpus | Representative portal pages used to measure detection accuracy | New |

---

## Success Criteria

- **SC-001**: On the FR-L-012 fixture corpus, every one of the 13 configured languages presented without a declared language attribute is correctly identified from page text. No configured language is misclassified as another language and none returns `unknown`.
- **SC-002**: For pages in languages outside the configured set, at least 90% are identified with their own language code and 100% are kept out of the supported set — that is, none is classified as any supported language. Every one of them raises a human language decision.
- **SC-003**: Zero pages in the corpus are classified as English unless English is the actual language of the page's main content. The unconditional English fallback is provably gone.
- **SC-004**: Pages that cannot be determined return `unknown` and reach the human decision gate; the gate presents "language could not be determined" distinctly from a named unsupported language.
- **SC-005**: Detection adds no more than 100 ms per unit at the 95th percentile after process warm-up, and performs zero network requests and zero model calls, verifiable under network isolation.
- **SC-006**: A language code added to `AIQ_SUPPORTED_LANGUAGES` becomes usable for gating with no change to detection code.
- **SC-007**: For any classification, an operator can determine after the fact — from telemetry or the existing trace span — whether the result came from the declared attribute or from text analysis, and with what confidence, without re-fetching the page.
- **SC-008**: The full existing test suite passes unmodified.

---

## Assumptions

- Portal pages are fetched as HTML and the existing text-extraction dependency in the project remains available for stripping markup.
- `AIQ_SUPPORTED_LANGUAGES` continues to be expressed as lowercase ISO 639-1 codes, matching the `.env` value `en,es,fr,de,pt,it,nl,ru,zh,ja,ko,ar,hi`.
- The declared-attribute-first precedence is a deliberate product decision carried forward from the existing behaviour, not an accident to be revisited here; contradiction between a declared attribute and page content is accepted as a known blind spot for this feature.
- The human language-decision gate has capacity for whatever increase in volume more honest detection produces. Correct classification is expected to *reduce* the volume of wrongly-gated units and *increase* the volume of correctly-gated ones; the net effect is not predicted here.
- Detection precision is measured against the fixture corpus, not against live portals, since live portal content changes.
- A default confidence threshold and ambiguity margin will be chosen from measured corpus behaviour during planning; the requirements do not presuppose particular values.
- One detection per unit, on the first fetched page, remains the right granularity. Per-page detection across a multi-page assessment is not introduced.

---

## Dependencies

- `AIQ_SUPPORTED_LANGUAGES` configuration (FR-014), already present.
- The language-decision gate and its router (FR-015–FR-020), already implemented; consumed unchanged.
- The `language_detection` tracing span (FR-T-002) and stage event log, already present; extended with the FR-L-010 detail.
- A fixture corpus of representative portal HTML, to be assembled as part of this feature.
- A new runtime dependency: a pure-Python statistical language-identification library with a bundled model and no compiled extension (e.g. `py3langid`) — see Clarifications. License and exact package selection to be confirmed during planning.

---

## Out of Scope

- Translation of portal content, and the best-effort confidence cap that accompanies it (FR-018) — already specified and implemented elsewhere.
- Changes to the language-decision workflow, its response window, its escalation paths, or the review surface that presents it.
- Cross-checking a declared `<html lang>` attribute against detected page content, or overriding a declared attribute that appears wrong.
- Per-page or per-section language detection within a single assessment unit.
- Distinguishing script variants (Simplified vs. Traditional Chinese) or regional dialects.
- Detecting the language of PDFs, attachments, or other non-HTML resources linked from a portal.
- Expanding `AIQ_SUPPORTED_LANGUAGES` itself, or the language-coverage evaluation of the configured models that determines its contents — a project activity, not a system capability.
