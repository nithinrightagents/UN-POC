# Implementation Plan: Multi-Language Detection for Portal Pages

**Feature Directory**: `specs/003-multi-language-detection`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-08-14
**Status**: Superseded — see [spec.md](./spec.md) for the current design and code pointers
**Branch**: `main` (see Notes)

> This plan (py3langid detector, unchanged human gate per FR-L-013) was
> fully implemented, then superseded the same day by a direct user
> instruction rejecting the detector package and the human gate in favor of
> an LLM-inline report checked against `AIQ_SUPPORTED_LANGUAGES` with a hard
> escalation on mismatch. See the notice at the top of spec.md.

## Summary

The language-decision gate (spec 001, FR-015–FR-020) is only as trustworthy as the detector feeding it, and today's detector (`shared/tools/language.py::detect_language`) silently defaults untagged Latin-script pages to English and returns bare `"unknown"` for everything else — meaning 8 of the 13 configured languages, and every language *outside* the configured set (the case the gate exists for), are effectively undetectable from page content.

This feature replaces the text-analysis fallback path with `py3langid`, a pure-Python statistical language identifier covering 97 languages including all 13 configured plus the out-of-set languages the spec calls out (Turkish, Polish, Thai, Swahili). The declared `<html lang>` attribute remains the first, highest-confidence signal, unchanged in precedence. Text analysis runs only when that attribute is absent or malformed, strips common boilerplate containers before classifying, and returns the explicit sentinel `"unknown"` — never `"en"` — whenever the minimum-text floor isn't met or the top candidate isn't confidently separated from the runner-up.

Detection is the entire surface of change. The human language-decision gate, its pending/authorized/declined/expired lifecycle, the best-effort confidence cap, and every existing test covering that gate are required to be unchanged (FR-L-013) — this was confirmed explicitly during `/speckit-clarify` after a scope question raised the possibility of removing the human gate entirely; that possibility was rejected in favor of keeping it and only fixing what feeds it.

**Primary technical challenge**: this sits on a synchronous hot path (FR-L-009) between page fetch and the assessor run, once per unit, with a near-zero latency budget (SC-005: 100ms p95) and a hard "no network, no model call" constraint — so the mechanism choice had to weigh accuracy against dependency weight and cold-start cost, not just raw classification quality. See [research.md](./research.md) R1.

## Technical Context

| Dimension | Decision | Source |
|---|---|---|
| **Detection library** | `py3langid` (pure-Python fork of `langid.py`), constructed with `norm_probs=True` | [research.md](./research.md) R1, R2 — resolved by `/speckit-clarify`, 2026-08-14 |
| **Declared-attribute precedence** | Unchanged: `<html lang>` checked first; text analysis is fallback-only | spec.md FR-L-005; carried forward from existing `detect_language` behavior |
| **Confidence signal** | Normalized top-candidate probability from `.rank(text)` | [research.md](./research.md) R2 |
| **Ambiguity handling** | Top-2 candidate margin check, configurable threshold | [research.md](./research.md) R3 |
| **Minimum text floor** | Character count of boilerplate-stripped visible text, configurable threshold | [research.md](./research.md) R4 |
| **Boilerplate suppression** | Strip `<script>/<style>/<noscript>/<nav>/<header>/<footer>/<aside>`; prefer `<main>`/`<article>` if present | [research.md](./research.md) R5 |
| **HTML parsing** | `BeautifulSoup` (already a dependency; unchanged) | existing `shared/tools/language.py` |
| **Result shape** | New `LanguageDetectionResult` dataclass + `detect_language_detailed()`; existing `detect_language() -> str` preserved as a thin wrapper | [research.md](./research.md) R7; [data-model.md](./data-model.md) |
| **New configuration** | `AIQ_LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD`, `AIQ_LANGUAGE_DETECTION_MARGIN_THRESHOLD`, `AIQ_LANGUAGE_DETECTION_MIN_TEXT_CHARS` | [contracts/configuration.md](./contracts/configuration.md) |
| **Telemetry integration** | `scheduler.py`'s existing `language_detection` LangSmith span and `stage_log.timed` block are extended with `source`/`confidence`/`text_length`, satisfying SC-007 | [data-model.md](./data-model.md) §Relationships |
| **Fixture corpus** | Real captured HTML snapshots of actual government portal pages, static files under `tests/fixtures/language_detection/` | [research.md](./research.md) R8 — resolved by `/speckit-clarify`, 2026-08-14 |
| **New dependency** | `py3langid` added to `pyproject.toml` main dependencies | [research.md](./research.md) R9 |
| **Testing** | `pytest`, new `tests/unit/test_language_detection.py`; existing gate/router/scheduler tests pass unmodified | [quickstart.md](./quickstart.md) |
| **Target scale** | One `detect_language()` call per unit, same call site, same frequency as today — no change in call volume | spec.md FR-L-009 |

**No unresolved NEEDS CLARIFICATION.** The `/speckit-clarify` session on 2026-08-14 resolved the two items the spec deliberately deferred to clarification (detection mechanism, fixture corpus provenance) and confirmed a third point raised mid-session (the human gate stays). Two items remain intentionally deferred past planning into implementation — see Deferred below — because their correct values depend on data (the fixture corpus) that doesn't exist yet.

**Deferred to implementation** (not blocking design, both configurable so no code change is needed later):
- `AIQ_LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD` and `AIQ_LANGUAGE_DETECTION_MARGIN_THRESHOLD` default values — starting points given in [contracts/configuration.md](./contracts/configuration.md), to be tuned against the fixture corpus once built.
- `AIQ_LANGUAGE_DETECTION_MIN_TEXT_CHARS` default value — same.

### Relationship to spec 001 and 002

- **Spec 001** (`FR-015`–`FR-020`) defines the language-decision gate this feature feeds. Every requirement of that gate — pending/authorized/declined/expired lifecycle, the 48-hour default window, the best-effort confidence cap — is a hard dependency, consumed unchanged (FR-L-013). This plan does not touch `shared/state/entities.py::LanguageDecision` or `orchestration/routers/language_decision.py`.
- **Spec 002** (LangSmith tracing, `FR-T-002`) already wraps the `detect_language()` call site in a `language_detection` span. This feature's only touch to `scheduler.py` is widening what gets patched into that existing span's `outputs` — no new span, no new stage name, no change to span hierarchy.

## Constitution Check

**No constitution file exists** at `.specify/memory/constitution.md` (confirmed absent, same as spec 001's plan). As spec 001's plan established, the design is gated against the spec's own non-negotiables in its absence.

| Gate | Requirement | How the design satisfies it | Status |
|---|---|---|---|
| **No silent misclassification** | FR-L-003, FR-L-004 | The unconditional `"en"` fallback is deleted, not just deprioritized — there is no code path in the new decision procedure ([contracts/language-detection.md](./contracts/language-detection.md) §Decision procedure) that returns a language without either a matched declared attribute or a classifier result clearing both the confidence and margin thresholds. | PASS |
| **Detector reports the truth, gate decides policy** | FR-L-002 | The classifier is never restricted to the configured-language candidate set; `language_requires_decision()` (unchanged) is solely responsible for the supported/unsupported distinction. Detection and policy stay in separate functions with no shared mutable state. | PASS |
| **Hot path stays synchronous and local** | FR-L-009 | `py3langid`'s model loads once at import; every call is in-process, no `await`, no I/O. Verified by a dedicated performance quickstart scenario (Scenario 7) that asserts zero network/model calls via mock, not just by absence of `import httpx`-style code review. | PASS |
| **Existing gate behavior is a hard boundary** | FR-L-013 | `detect_language()`'s signature is unchanged (research R7); `language_requires_decision()`, `LanguageDecision`, and the whole scheduler gate flow are untouched files in this feature's diff. The full existing suite (`tests/unit`, `tests/contract`, `tests/integration`) is a required-pass gate before this feature is considered complete (SC-008, quickstart Scenario 8). | PASS |
| **Auditability of a classification** | FR-L-010, SC-007 | `LanguageDetectionResult`'s `source`/`confidence`/`text_length` flow into the existing `language_detection` trace span and stage event — both already durable, queryable records — with no new persisted entity and no new schema. | PASS |
| **Configuration externalized** | (spec 001 precedent, FR-072–FR-075) | All three new tunables are `Settings` fields sourced from `.env`, captured by the existing Configuration Snapshot mechanism with no per-field wiring required. No threshold is a literal in `language.py`. | PASS |

**Post-design re-evaluation**: see [Post-Design Constitution Re-check](#post-design-constitution-re-check).

## Project Structure

This feature's diff is small and touches no new top-level module — everything lands in files that already exist, plus one new test file and one new fixture directory.

```
src/
├── shared/
│   ├── tools/
│   │   └── language.py             # MODIFIED — new detection procedure (contracts/language-detection.md)
│   │                                #   adds: LanguageDetectionResult, detect_language_detailed()
│   │                                #   detect_language() becomes a thin wrapper, signature unchanged
│   └── config/
│       ├── settings.py             # MODIFIED — 3 new fields (contracts/configuration.md)
│       └── validation.py           # MODIFIED — range checks for the 3 new settings
│
└── orchestration/
    └── scheduler.py                # MODIFIED — language_detection span/stage_log now receive
                                     #   source/confidence/text_length (data-model.md §Relationships)
                                     #   NOT modified: the gate logic itself (language_requires_decision call,
                                     #   pending-decision creation, window-expiry check) — FR-L-013

tests/
├── unit/
│   └── test_language_detection.py  # NEW — contract + corpus-sweep + performance tests
│                                    #   (quickstart.md Scenarios 1–7)
└── fixtures/
    └── language_detection/         # NEW — real captured portal-page snapshots (research R8)
                                     #   one per required FR-L-012 case

pyproject.toml                      # MODIFIED — + py3langid dependency (research R9)
```

**What is explicitly NOT touched**, and why that boundary matters:

- `orchestration/routers/language_decision.py` — the gate's policy logic (`language_requires_decision`, decision resolution functions). This feature changes what `detect_language` reports, never what the gate does with the report (FR-L-002's separation of concerns).
- `shared/state/entities.py::LanguageDecision` — no new field. The record already carries `detected_language`; it now just receives better values.
- Any database schema/migration — none required (data-model.md §No changes to existing entities).
- `shared/tools/__init__.py`'s public export of `detect_language` — the export stays; `detect_language_detailed` is added alongside it, not in place of it.

## Phase 0 — Research

Complete. See [research.md](./research.md). Nine decisions recorded, each with rationale and alternatives considered:

| # | Decision |
|---|---|
| R1 | `py3langid` as the detection mechanism — resolved via `/speckit-clarify` |
| R2 | Normalized probabilities (`norm_probs=True`) as the confidence signal |
| R3 | Top-2 margin check for ambiguity handling |
| R4 | Minimum text-length floor before classification is attempted |
| R5 | Tag-based boilerplate suppression, `<main>`/`<article>` preference |
| R6 | `<html lang>` well-formedness anchored to a real language-code list |
| R7 | `LanguageDetectionResult` + backward-compatible `detect_language()` wrapper |
| R8 | Fixture corpus from real captured portal snapshots — resolved via `/speckit-clarify` |
| R9 | `py3langid` added as a direct `pyproject.toml` dependency |

## Phase 1 — Design & Contracts

Complete.

- **[data-model.md](./data-model.md)** — the one new value type (`LanguageDetectionResult`), the three new configuration fields, the fixture corpus shape, and an explicit list of entities confirmed unchanged.
- **[contracts/](./contracts/)**
  - [language-detection.md](./contracts/language-detection.md) — `detect_language()` / `detect_language_detailed()` contract, including the normative step-by-step decision procedure and the failure-mode guarantee (never raises, never silently defaults to English).
  - [configuration.md](./contracts/configuration.md) — the three new `AIQ_LANGUAGE_DETECTION_*` parameters, their starting defaults, and why those defaults are explicitly provisional.
- **[quickstart.md](./quickstart.md)** — eight runnable validation scenarios mapped 1:1 to spec.md's User Scenarios, plus a manual smoke check.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Fixture corpus doesn't exist yet** | Every accuracy claim (SC-001–SC-003) and every threshold default (contracts/configuration.md) is unverifiable until real portal pages are captured and labeled. This is the single largest source of schedule risk in `tasks.md`. | Sequenced explicitly as an early, standalone task in `tasks.md` (research R8's "open action item"), before any test that depends on it. Nothing else in this feature blocks on it — the detection code itself can be written and unit-tested against small inline HTML strings first. |
| **`py3langid` accuracy on short/noisy government-portal text is unproven** | The library's published coverage is for its 97 languages generally, not specifically validated against this project's actual portal HTML. If real-page accuracy is materially worse than expected, SC-001 (100% of 13 configured languages correctly identified) may not be met out of the box. | The three thresholds (confidence, margin, min-text) are exactly the tuning surface for this — deliberately left configurable and un-finalized (Deferred, above) rather than hard-coded, so a corpus-revealed accuracy gap is a config change, not a redesign. If accuracy is still insufficient after tuning, R5's boilerplate-suppression scope (currently tag-based only) is the next lever, per research R5's own noted fallback. |
| **License/dependency approval** | `py3langid` (BSD-2-Clause) is a new runtime dependency; if this project has a dependency-approval process not visible in the repo, it could block adoption. | Flagged explicitly in research R1 and R9. Low risk given `beautifulsoup4` (MIT) and other permissive-licensed dependencies are already present with no apparent approval friction (e.g. `langsmith` was added for spec 002 without incident). |
| **Boilerplate suppression (R5) is a first pass, not exhaustive** | Tag-based stripping (`<nav>`, `<footer>`, etc.) will not help on portals built entirely from generic `<div>`s with no semantic markup — a real possibility on older government sites. | Explicitly scoped as a Deferred Design Decision in the spec and flagged in research R5 as revisitable; the fixture corpus (once built) will surface whether this is a real gap, and a content-scoring fallback is the named next step if so — not a redesign of the overall detection pipeline. |

## Notes

- **Branch**: work continues on `main`. No `before_plan`/`before_specify` git hook is configured in this project (`.specify/extensions.yml` does not exist), so no feature branch was created automatically; this matches how `specs/003-multi-language-detection`'s own `/speckit-specify` and `/speckit-clarify` steps proceeded.
- **Graphify skipped.** `graphify` (a skill/graph-management CLI, version 0.9.22) is present in this environment but its subcommands (`update`, `cluster-only`) are oriented around building a full-repo AST/cluster graph, which was unnecessary here: this feature's affected surface is one module (`shared/tools/language.py`), its one call site (`orchestration/scheduler.py`), and one config file (`shared/config/settings.py`) — all read directly during Phase 0/1 research rather than requiring a repo-wide structural map to locate.
- Spec 001's `plan.md` and this plan share one useful precedent worth restating: **configuration over code for anything likely to need tuning**. Just as spec 001 made the confidence acceptance threshold and best-effort ceiling configurable rather than fixed, this feature's three new thresholds follow the same posture — correct by construction is less important here than correct by measurement, and measurement requires the values to be changeable without a redeploy.

## Post-Design Constitution Re-check

Re-evaluated after data-model.md and contracts/ were written. All six gates from the initial Constitution Check still PASS; two are worth calling out as strengthened by the design work rather than merely preserved:

- **No silent misclassification** moved from "the fallback is removed" (a code-deletion claim) to a positively specified decision procedure ([contracts/language-detection.md](./contracts/language-detection.md) §Decision procedure) with seven explicit, ordered steps and a named result for every one of them — there is no implicit "else" branch left that could reintroduce a silent default under a future edit, because every branch in the procedure is enumerated and every branch's output type is documented.
- **Auditability of a classification** was verified against the *existing* telemetry schema rather than assumed, and the check caught a real constraint: `StageEventLog.record()` has no generic kwargs channel (only `agent_index`/`round_number`), so the three new fields ride on the already-free-form `unit_ref` dict instead — mutated in place after detection runs, before the `timed()` context manager's `finally` clause fires. `safe_trace`'s `outputs` parameter needed no such workaround. Either way, SC-007 is satisfiable with zero schema changes to either telemetry system. See data-model.md §Relationships for the exact mechanism.

One design consequence worth recording: **FR-L-005 and FR-L-010 interact.** When the declared attribute wins (step 2 of the decision procedure), `text_length` is recorded as `0` and `confidence` as `None` — not omitted, but explicitly zero/null. This was a deliberate data-model choice (see [data-model.md](./data-model.md) validation rules) so that a telemetry consumer can distinguish "the declared attribute was trusted, text analysis never ran" from "text analysis ran but found nothing" (which would show a non-zero `text_length` with `language="unknown"`) — the two are different diagnostic stories and the result shape keeps them distinguishable without extra fields.
