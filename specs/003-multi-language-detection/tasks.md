# Tasks: Multi-Language Detection for Portal Pages

**Feature**: `003-multi-language-detection`
**Spec**: [spec.md](spec.md)
**Plan artifacts**: [plan.md](plan.md) | [research.md](research.md) | [data-model.md](data-model.md) | [contracts/language-detection.md](contracts/language-detection.md) | [contracts/configuration.md](contracts/configuration.md) | [quickstart.md](quickstart.md)
**Generated**: 2026-08-14

> **Superseded 2026-08-14** — every task below was completed, then its
> deliverables (the `py3langid` detector, its settings, its fixture corpus
> and unit tests) were removed the same day after the user rejected that
> architecture in favor of an LLM-inline language report checked by
> `orchestration/scheduler.py`. The `[X]` marks below record what was
> actually built and later superseded, not current state. See the notice at
> the top of [spec.md](spec.md) and `tests/unit/test_language_support_check.py`
> for what replaced it.

**Note on story labels**: spec.md organizes requirements as `## Actors` + numbered `Scenario N` rather than prioritized `User Story N (Priority: PN)` sections (this matches spec 002's convention for infrastructure/correctness features, not spec 001's actor-driven convention). The four story groupings below (US1–US4) are this plan's own prioritized decomposition of the spec's scenarios into independently testable increments, the same approach spec 002's `tasks.md` used.

---

## Implementation Strategy

MVP-first delivery in four increments, each independently testable per its own quickstart scenario(s):

1. **Increment 1** (Phase 1-2): Setup + foundational scaffolding — dependency, config fields, dataclass shell. No detection-behavior change yet.
2. **Increment 2** (Phase 3, US1 — P1, the MVP): Swap the detection mechanism in. Fixes the core bug — all 13 configured languages, declared-attribute precedence preserved.
3. **Increment 3** (Phase 4, US2 — P2): Out-of-set languages reported specifically — the case that matters most for the human gate.
4. **Increment 4** (Phase 5, US3 — P3): Safety net — minimum-text floor, ambiguity margin, boilerplate suppression refined to never guess.
5. **Increment 5** (Phase 6, US4 — P4): Telemetry — detection basis auditable after the fact.
6. **Polish** (Phase 7): Corpus-wide accuracy sweep, performance budget, full regression pass, threshold tuning.

---

## Phase 1: Setup

> Goal: Add `py3langid` as a dependency. Zero detection-logic changes.

- [X] T001 Add `py3langid>=0.2.2` to `dependencies` list in `pyproject.toml`
- [X] T002 [P] Install updated dependencies (`pip install -e .` from repo root) and verify `import py3langid` resolves with no conflicts

---

## Phase 2: Foundational — Scaffolding

> Goal: Data shape and configuration surface exist before any story wires real behavior into them.
>
> **Must complete before Phase 3.** All story phases below build on these.

- [X] T003 Add `LanguageDetectionResult` frozen dataclass (`language: str`, `source: Literal["declared_attribute", "text_analysis", "undetermined"]`, `confidence: float | None`, `text_length: int`) to `src/shared/tools/language.py`, per [data-model.md](data-model.md)
- [X] T004 [P] Add three new fields to the `Settings` dataclass in `src/shared/config/settings.py` under a `# --- Language detection ---` section: `language_detection_confidence_threshold: float = 0.60`, `language_detection_margin_threshold: float = 0.05`, `language_detection_min_text_chars: int = 40`; and three matching entries in `_ENV_MAP`: `"language_detection_confidence_threshold": ("AIQ_LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD", float)`, `"language_detection_margin_threshold": ("AIQ_LANGUAGE_DETECTION_MARGIN_THRESHOLD", float)`, `"language_detection_min_text_chars": ("AIQ_LANGUAGE_DETECTION_MIN_TEXT_CHARS", int)` — per [contracts/configuration.md](contracts/configuration.md)
- [X] T005 [P] Add range validation for the three new settings to `validate_settings()` in `src/shared/config/validation.py`, following the existing `for name, value, lo, hi in [...]` pattern already used for `AIQ_VALIDATION_QUALITY_THRESHOLD` etc.: confidence and margin thresholds in `[0.0, 1.0]`, min text chars `>= 1`
- [X] T006 [P] Create `tests/fixtures/language_detection/` directory with a `README.md` (mirroring the convention in `tests/fixtures/resolution/README.md`) documenting the required fixture set from FR-L-012, and an empty `manifest.json` mapping `{filename: {"expected_language": <code or "unknown">, "case": <tag>}}` for the corpus-sweep test to read

---

## Phase 3: US1 (P1) — Core detection accuracy for configured languages

> Goal: Replace the stopword/CJK heuristic with `py3langid`; declared-attribute precedence and validation behave per FR-L-005. This is the MVP — it directly fixes the bug the spec opens with (untagged German/Italian/Dutch no longer default to English).
>
> **Independent test**: given untagged HTML in any of the 13 configured languages, `detect_language()` returns the correct code, never `"en"` unless the page is actually English. Given `<html lang="ko">`, returns `"ko"` without invoking the classifier. Given a malformed/empty `lang` attribute, falls through to text analysis correctly.

- [X] T007 [US1] Implement `_extract_visible_text(soup: BeautifulSoup) -> str` in `src/shared/tools/language.py` (research R5): `.decompose()` all `<script>`, `<style>`, `<noscript>`, `<nav>`, `<header>`, `<footer>`, `<aside>` elements; if a non-empty `<main>` or `<article>` remains, return its text; otherwise return the remaining body text
- [X] T008 [US1] Implement `_declared_language(soup: BeautifulSoup) -> str | None` in `src/shared/tools/language.py` (research R6): read the `<html>` tag's `lang` attribute, split on `-` to get the primary subtag, lowercase it, validate it against `py3langid`'s supported-language code set (`py3langid.langid.MODEL_LANGS` or equivalent per the installed version's API — confirm exact attribute name against the installed package), return the normalized code if recognized, else `None`
- [X] T009 [US1] Implement classifier construction and `_classify_text(text: str) -> list[tuple[str, float]]` in `src/shared/tools/language.py`: build a module-level `py3langid.langid.LanguageIdentifier` (or equivalent factory) once at import time with `norm_probs=True`; `_classify_text` calls its `.rank(text)` and returns the full ranked list
- [X] T010 [US1] Implement `detect_language_detailed(html: str) -> LanguageDetectionResult` in `src/shared/tools/language.py` per [contracts/language-detection.md](contracts/language-detection.md) §Decision procedure steps 1–3, 5, 7 only (declared-attribute check via T008 → `_extract_visible_text` via T007 → `_classify_text` via T009 → return the top-ranked candidate, normalized per FR-L-011 so any Chinese script variant returns `"zh"`); wrap the whole function body in a `try/except Exception` per the contract's Failure mode, logging a `WARNING` and returning `language="unknown", source="undetermined"` on any internal error
- [X] T011 [US1] Replace the body of `detect_language(html: str) -> str` in `src/shared/tools/language.py` with `return detect_language_detailed(html).language`; delete the old `_STOPWORDS` table and stopword-frequency logic entirely
- [X] T012 [US1] Export `detect_language_detailed` and `LanguageDetectionResult` from `src/shared/tools/__init__.py` (add to both the `from shared.tools.language import ...` line and `__all__`)
- [X] T013 [P] [US1] Gather real captured HTML snapshots (research R8) for each of the 13 configured languages (`en, es, fr, de, pt, it, nl, ru, zh, ja, ko, ar, hi`) without a declared `lang` attribute, plus one page with a *wrong* declared attribute and one with a *malformed/empty* declared attribute, into `tests/fixtures/language_detection/`; add each to `manifest.json` with its `expected_language` and a `case` tag
- [X] T014 [US1] Create `tests/unit/test_language_detection.py` (marked `@pytest.mark.unit`) with: a parametrized test over the 13-language fixture subset from T013 asserting `detect_language(html) == expected`; a test for Scenario 6 (declared attribute wins — assert the classifier is not invoked, e.g. via `monkeypatch`/call-count on `_classify_text`); a test for Scenario 7 (malformed attribute falls through to the correct text-analysis result)

---

## Phase 4: US2 (P2) — Out-of-set languages are identified specifically

> Goal: A page in a language outside `AIQ_SUPPORTED_LANGUAGES` returns its own code — not `"en"`, not the nearest supported language, not `"unknown"` merely for being unsupported. This is the case the spec identifies as mattering most, since it's what the human gate exists for.
>
> **Independent test**: out-of-set fixtures (Turkish, Polish, Thai) return `tr`, `pl`, `th` respectively via `detect_language()`; `language_requires_decision()` correctly flags each as requiring a human decision, and each configured-language fixture from US1 correctly does not.

- [X] T015 [P] [US2] Gather real captured HTML snapshots for at least three out-of-set languages (e.g. Turkish, Polish, Thai) into `tests/fixtures/language_detection/`, add each to `manifest.json`
- [X] T016 [US2] Add a parametrized test to `tests/unit/test_language_detection.py` over the out-of-set fixtures from T015 asserting `detect_language(html)` returns the fixture's own code — never `"en"`, never `"unknown"` (Scenario 2)
- [X] T017 [US2] [P] Add a test to `tests/unit/test_language_detection.py` (or `tests/integration/` if it more naturally sits alongside existing language-gate integration coverage) asserting `language_requires_decision(detect_language(html), settings.supported_languages)` is `True` for every out-of-set fixture (T015) and `False` for every configured-language fixture (T013) — confirms `orchestration/routers/language_decision.py` needs no change and correctly consumes the improved detector output

---

## Phase 5: US3 (P3) — Uncertain pages return an explicit `unknown`, never a guess

> Goal: the minimum-text floor and confidence/margin ambiguity checks are enforced, and boilerplate does not decide a page's language.
>
> **Independent test**: a too-short fixture and a genuinely bilingual fixture both return `"unknown"` via `detect_language()`, with `detect_language_detailed()` distinguishing `source="undetermined"` (too short) from `source="text_analysis"` (ambiguous but classified); a Dutch page with English nav/footer boilerplate still returns `"nl"`.

- [X] T018 [US3] Implement the minimum-text-floor short-circuit (contract step 4) in `detect_language_detailed()` in `src/shared/tools/language.py`: after `_extract_visible_text`, if `len(text) < settings.language_detection_min_text_chars`, return `language="unknown", source="undetermined", confidence=None, text_length=len(text)` without calling `_classify_text`
- [X] T019 [US3] Implement the confidence-threshold and top-2-margin ambiguity check (contract step 6) in `detect_language_detailed()` in `src/shared/tools/language.py`: after `_classify_text` returns ranked candidates, if the top candidate's probability is below `settings.language_detection_confidence_threshold`, or the gap between the top two candidates' probabilities is below `settings.language_detection_margin_threshold`, return `language="unknown", source="text_analysis", confidence=<top probability>, text_length=len(text)`
- [X] T020 [P] [US3] Gather real captured HTML snapshots for: a boilerplate-heavy non-English page (English nav/footer/cookie-banner text around non-English main content — the spec's own Scenario 4 example is Dutch), a too-short/near-empty page, and a genuinely bilingual page (e.g. roughly equal French/English content), into `tests/fixtures/language_detection/`, add each to `manifest.json`
- [X] T021 [US3] Add tests to `tests/unit/test_language_detection.py` for Scenarios 4, 5, 8 using the T020 fixtures: boilerplate fixture → correct main-content language; too-short fixture → `unknown`/`source="undetermined"`; bilingual fixture → `unknown`/`source="text_analysis"`

---

## Phase 6: US4 (P4) — Detection basis is auditable in telemetry

> Goal: an operator can determine, after the fact, whether a classification came from the declared attribute or text analysis, and with what confidence, from the existing `language_detection` trace span and stage event — without re-fetching the page (SC-007).
>
> **Independent test**: for a unit that goes through the language-decision gate, the `language_detection` LangSmith span's `outputs` and the corresponding stage event's `unit_ref` both contain `source`, `confidence`, and `text_length` matching what `detect_language_detailed()` returned.

- [X] T022 [US4] In `process_unit()` in `src/orchestration/scheduler.py`: change the call from `detect_language(page_result.html)` to `detect_language_detailed(page_result.html)`; keep `unit_data["detected_language"]` assigned from the result's `.language` field (no change to any downstream gate logic); update the import at the top of the file accordingly
- [X] T023 [US4] In the same block in `src/orchestration/scheduler.py`: build the `unit_ref` dict passed to `stage_log.timed("language_detection", unit_ref)` as a local variable *before* entering the `with` block (it is currently an inline literal), then — inside the block, after the detection result is available — mutate that same `unit_ref` dict to add `detected_language_source`, `detected_language_confidence`, `detected_language_text_length` before the block exits, so `StageEventLog.record()`'s `finally`-clause write captures them (see [data-model.md](data-model.md) §Relationships for why this goes through `unit_ref` rather than `record()`'s kwargs)
- [X] T024 [US4] In the same block: extend `lang_span.patch(outputs={"detected_language": detected_language})` to also include `"source"`, `"confidence"`, `"text_length"` from the detailed result
- [X] T025 [US4] Add a test (in `tests/unit/test_language_detection.py` or alongside existing scheduler/LangSmith tests in `tests/unit/test_langsmith_tracing.py`, whichever this project's existing convention groups scheduler-level telemetry assertions under) confirming that after `process_unit()` runs against a declared-attribute fixture and a text-analysis fixture, the recorded stage event's `unit_ref` and the trace span outputs both carry the correct `source`/`confidence`/`text_length` for each case

---

## Phase 7: Polish & Cross-Cutting Concerns

> Goal: corpus-wide accuracy proof, performance budget verification, full regression safety, and threshold tuning. Depends on every fixture gathered in T013, T015, T020 existing.

- [X] T026 [P] Add a `corpus_sweep` test to `tests/unit/test_language_detection.py` that iterates every entry in `tests/fixtures/language_detection/manifest.json`, asserting `detect_language(html) == expected_language` for each — this single test is the executable form of SC-001, SC-002, SC-003 (all 13 configured languages correct, ≥90% of out-of-set languages correctly named, zero incorrect English classifications)
- [X] T027 [P] Add a `performance` test to `tests/unit/test_language_detection.py`: after a warm-up call (to exclude first-import model load), time `detect_language_detailed()` over every corpus fixture and assert p95 latency is under 100ms (SC-005); separately assert zero calls to any network-capable client (e.g. via `monkeypatch` raising on `httpx`/`playwright` entry points) during detection
- [X] T028 Run the full existing suite — `pytest tests/unit tests/contract tests/integration -v` — and confirm every test outside `tests/unit/test_language_detection.py` and `tests/fixtures/language_detection/` passes unmodified (SC-008, FR-L-013); fix regressions by adjusting only the new detection code, never the pre-existing gate/router/scheduler tests
- [X] T029 Review the T026 corpus-sweep results and tune the three defaults in `src/shared/config/settings.py` (`language_detection_confidence_threshold`, `language_detection_margin_threshold`, `language_detection_min_text_chars`) if the starting values from T004 under- or over-trigger `unknown` against the real corpus; update the documented defaults in [contracts/configuration.md](contracts/configuration.md) to match whatever ships

---

## Dependency Graph

```
T001 → T002
T003 (independent of T001/T002)
T004 → T005
T006 (independent)
T003, T004 → T007, T008, T009 (parallel — different helper functions, same file, but no shared state)
T007, T008, T009 → T010 → T011 → T012

T013 (independent — data-gathering, can start immediately alongside T001-T012)
T015 (independent — data-gathering, can start immediately alongside T001-T012)
T020 (independent — data-gathering, can start immediately alongside T001-T012)

T012, T013 → T014
T014, T015 → T016, T017 (parallel)
T004(settings) + T010 → T018 → T019
T019, T020 → T021
T011 (detect_language_detailed exists) → T022 → T023 → T024 → T025
T014, T016, T021 (fixtures + core logic complete) → T026, T027 (parallel)
T026, T027, T025 → T028 → T029
```

---

## Parallel Execution Opportunities

| Group | Tasks | Can run in parallel after |
|---|---|---|
| Setup | T001, T002 | — |
| Foundational | T003, T004, T005, T006 | T001/T002 (T003 doesn't even need the dependency installed, but is sequenced here for clarity) |
| Fixture gathering | T013, T015, T020 | — (data-gathering only; can start immediately, in parallel with all of Phase 1-2 and the US1 coding tasks) |
| US1 helpers | T007, T008, T009 | T003 |
| US2 tests | T016, T017 | T015 |
| US4 scheduler edits | T023, T024 | T022 (same file, sequential in practice despite no formal file conflict) |
| Polish verification | T026, T027 | T021, T025 |

Note: T007–T011 and T018–T019 all edit `src/shared/tools/language.py` sequentially within their own story phase — genuine same-file parallelism is limited to helper functions that don't yet call each other (T007/T008/T009). Cross-story tasks (US1 vs US2 vs US3 vs US4) are sequential by design: each story adds a step to the same `detect_language_detailed()` decision procedure, not independent files.

---

## Story → Task Mapping

| Story | Priority | Requirements | Tasks | Independent test criteria |
|---|---|---|---|---|
| US1 | P1 (MVP) | FR-L-001, FR-L-003, FR-L-005, FR-L-006, FR-L-011 | T007–T014 | Untagged pages in all 13 configured languages return their correct code; declared attribute still wins and is validated; malformed attribute falls through correctly |
| US2 | P2 | FR-L-002 | T015–T017 | Out-of-set language fixtures return their own code, never `en`/`unknown`; gate correctly flags them for human decision |
| US3 | P3 | FR-L-004, FR-L-007, FR-L-008 | T018–T021 | Too-short and bilingual fixtures return `unknown` with the correct `source` distinguishing why; boilerplate doesn't override main-content language |
| US4 | P4 | FR-L-010, SC-007 | T022–T025 | Trace span and stage event both carry source/confidence/text_length after a real gate run |

---

## MVP Scope

**Minimum viable fix (the bug report itself)**: T001–T014 — the core mechanism swap. At this point, every configured language is correctly detected from page text and the declared-attribute path is unchanged and validated. This alone resolves the spec's headline example (untagged German defaulting to English).

**Full feature**: T001–T029 — adds out-of-set specificity (US2), the "never guess" safety net (US3), telemetry auditability (US4), and the corpus-wide proof + tuning pass (Polish).

**Recommended sequencing note**: T013, T015, and T020 (fixture-gathering) are data-gathering, not coding, tasks — flagged in [plan.md](plan.md) Risks as the largest schedule risk. Consider starting fixture collection for all three phases in parallel with T001–T012's coding work, since gathering real government-portal pages doesn't depend on the detection code being written yet, only on knowing what cases are needed (already fully specified in FR-L-012).

---

## Format Validation

All 29 tasks follow `- [ ] T0NN [P?] [USn?] Description with exact file path(s)`. Setup (T001–T002) and Foundational (T003–T006) carry no story label per the task-format rules. Polish (T026–T029) carries no story label. Every US-labeled task (T007–T025) names its story. Every task names at least one concrete file path.
