# Research: Multi-Language Detection for Portal Pages

**Feature Directory**: `specs/003-multi-language-detection`
**Spec**: [spec.md](./spec.md)

Nine decisions, each with rationale and alternatives considered. R1 was pre-settled by the `/speckit-clarify` session (see spec.md `## Clarifications`); it is restated here with the supporting detail that didn't belong in the spec.

---

## R1 — Detection mechanism: `py3langid`

**Decision**: Replace the stopword/CJK-ratio heuristic in `shared/tools/language.py` with `py3langid`, a maintained, pure-Python fork of Google's `langid.py`.

**Rationale**:
- **Coverage matches the requirement exactly.** `py3langid`'s bundled model covers 97 languages, including all 13 configured languages (`en, es, fr, de, pt, it, nl, ru, zh, ja, ko, ar, hi`) *and* the languages named in the spec's out-of-set edge cases (Turkish, Polish, Thai, Swahili). No per-language rule-writing is needed — FR-L-001's "dynamic, not hard-wired" requirement falls out of the library's existing coverage rather than requiring new code per language added to `AIQ_SUPPORTED_LANGUAGES`.
- **No compiled extension.** The model is a serialized naive-Bayes classifier over byte n-grams, loaded from a bundled data file at import time — pure Python, no C-extension build step. This matters concretely on this project's Windows development environment, where a `fasttext` (C++ extension) dependency has historically been a source of wheel/build friction.
- **No network, no per-call cost.** The model loads once per process (`import py3langid` or `py3langid.langid.LanguageIdentifier.from_modelstring(...)`) and every subsequent `.classify()` / `.rank()` call is in-process and fast (single-digit milliseconds for typical page-text lengths) — satisfies FR-L-009 directly.
- **Gives a confidence signal, not just a label.** `py3langid.rank(text)` returns every candidate language ranked by score. Constructed with `norm_probs=True`, scores are normalized probabilities in `[0, 1]` summing to 1 across all candidates — usable directly as the FR-L-007 confidence measure and margin computation (top-1 vs. top-2 probability gap).

**Alternatives considered**:
| Option | Why not chosen |
|---|---|
| `fasttext` `lid.176` compressed model | Best raw accuracy of the options evaluated, and the compressed model file is small (~1 MB), but the `fasttext` Python package is a C++ extension — adds build/wheel complexity on Windows dev machines, which this project's contributors use, for an accuracy gain the fixture corpus (once built) may not show as material at the scale of a per-unit gate check. |
| `langdetect` (Python port of Google's Java detector) | Pure Python, mature, widely used. Its Naive-Bayes n-gram model is well documented but is known to be less stable on short or noisy input than `langid`-family detectors — a direct conflict with FR-L-008 (short-page handling) and FR-L-006 (noisy government-portal markup). Its non-deterministic seeding (results can vary run-to-run without a fixed seed) is also an awkward fit for a corpus-verified accuracy claim (SC-001–SC-003). |
| Extend the in-repo stopword/CJK heuristic | Zero new dependency. Rejected because it does not scale to 8 more languages without writing and maintaining a bespoke rule set per script, and it structurally cannot satisfy FR-L-002 (report *any* out-of-set language, not just the configured ones) — a fixed stopword table only ever recognizes what it was built for. This was the mechanism responsible for the bug this feature exists to fix. |

**Licensing note**: `langid.py` (and by extension `py3langid`) is BSD-2-Clause. Confirm this against the project's dependency-approval process at implementation time; no conflict is expected given `beautifulsoup4` (MIT) and other permissive dependencies already in `pyproject.toml`.

---

## R2 — Confidence normalization

**Decision**: Construct the `py3langid` identifier with `norm_probs=True` so `.rank(text)` returns calibrated probabilities rather than raw log-likelihood scores.

**Rationale**: FR-L-007 requires a confidence measure compared against a configurable threshold, and a margin comparison between the top two candidates. Raw `langid` scores are unnormalized log-probabilities with no fixed scale, which makes a configured threshold meaningless across different text lengths. Normalized probabilities give a stable `[0, 1]` scale that a threshold and a margin can be defined against consistently.

**Alternatives considered**: Using raw scores with an empirically-tuned threshold — rejected because the threshold would need re-tuning whenever typical page-text length distribution shifts (e.g., a batch of unusually short pages), which normalized probabilities are specifically designed to avoid.

---

## R3 — Ambiguity margin

**Decision**: Take the top two entries from `.rank(text)`. If `top1_prob - top2_prob` is below a configurable margin threshold, return `unknown` regardless of how high `top1_prob` is on its own.

**Rationale**: Directly implements FR-L-007's bilingual-page handling (spec Scenario 8). A page with genuinely mixed French/English content can have both languages score highly and closely — accepting the top score alone would produce an arbitrary pick that happens to break ties by whatever the model's internal ordering does, not by genuine confidence.

**Alternatives considered**: Requiring only a single absolute confidence threshold — rejected because a page can have a high top-1 probability *and* a close second place (e.g., `fr: 0.51, en: 0.47`) simultaneously; an absolute threshold alone would accept this as confidently French when the signal is actually ambiguous.

---

## R4 — Minimum text length

**Decision**: Count characters of extracted, boilerplate-stripped visible text (not raw HTML). Below a configurable minimum (starting default: 40 characters, roughly one short sentence), return `unknown` without invoking the classifier at all.

**Rationale**: FR-L-008 requires this explicitly. `langid`-family classifiers degrade sharply on very short input because n-gram frequency signal is too sparse to separate candidates — returning a low-confidence classification here would just push the ambiguity into FR-L-007's threshold check with extra, uninformative work. Short-circuiting before classification is both correct and cheaper.

**Alternatives considered**: Relying on FR-L-007's confidence threshold alone to catch short pages — rejected because very short text can occasionally produce a spuriously high-confidence wrong classification (a handful of characters can coincidentally match one language's n-gram profile strongly). An explicit length floor is a more direct and legible safeguard, and it doubles as the documented answer to "why did this return unknown" for the shortest pages in the fixture corpus.

**Default value note**: 40 characters is a starting point for planning, not a final answer. Per the spec's Deferred Design Decisions, the shipped default is set from what the FR-L-012 real-page fixture corpus actually shows once assembled.

---

## R5 — Main-content extraction (boilerplate suppression)

**Decision**: Before classification, strip `<script>`, `<style>`, `<noscript>`, `<nav>`, `<header>`, `<footer>`, and `<aside>` elements from the parsed DOM. Prefer text inside `<main>` or `<article>` if either is present and non-empty after stripping. Otherwise, fall back to the full remaining body text (already boilerplate-stripped by the tag removal above).

**Rationale**: FR-L-006 requires that English nav/footer/cookie-banner text on a non-English page not decide the classification (spec Scenario 4). Removing the structurally-named boilerplate containers is a cheap, deterministic first pass that requires no new dependency (`BeautifulSoup`, already in use, does this natively via `.decompose()`). Preferring `<main>`/`<article>` when present adds a second layer of precision on portals that use semantic HTML5 markup, common enough on modern government sites to be worth the negligible extra cost.

**Alternatives considered**:
| Option | Why not chosen (as primary strategy) |
|---|---|
| Full Readability-style content-scoring algorithm (longest-text-block heuristics, link-density scoring) | More robust against div-soup pages with no semantic tags, but is meaningfully more code and CPU for a per-unit hot-path call (FR-L-009). Tag-based stripping handles the common government-portal case (real `<nav>`/`<footer>`) directly; a scoring fallback can be added later if the fixture corpus shows tag-based stripping isn't enough on div-soup pages. |
| No boilerplate suppression, classify full page text | Simplest, but directly fails Scenario 4 — the spec's own core example. Rejected outright as it does not satisfy FR-L-006. |

This is one of the two items the spec explicitly leaves as a Deferred Design Decision; this research resolves it to the tag-stripping approach as the initial implementation, revisitable if corpus results show it's insufficient.

---

## R6 — `<html lang>` well-formedness check

**Decision**: A declared language attribute is "well-formed" (FR-L-005) if, after taking the primary subtag (splitting on `-`), the value matches a known two- or three-letter ISO 639 code. Use `py3langid`'s own supported-language code list as the recognition set (it already needs to exist in-process for R1, so this adds no new data dependency), supplemented with a small fixed set of extra recognized codes if the declared value is a valid ISO 639-1/639-3 code outside `langid`'s coverage (in that case, the declared attribute is still trusted and returned as-is — FR-L-005 does not require the attribute's language to be one `py3langid` itself can detect from text).

**Rationale**: This keeps "well-formed" anchored to a real code list rather than a permissive regex (`[a-z]{2,3}`) that would accept placeholder junk like `"xx"` or `"zz"`. It reuses data already loaded for R1 rather than bundling a second language-code table.

**Alternatives considered**: A general-purpose BCP-47 parsing library — rejected as unnecessary weight; the spec's own well-formedness bar (non-empty, recognized primary subtag) doesn't need full BCP-47 grammar validation (extensions, private-use subtags, etc.), just the primary language subtag.

---

## R7 — Result shape and backward compatibility

**Decision**: Introduce a `LanguageDetectionResult` dataclass (language, source, confidence, text_length) and a new `detect_language_detailed(html) -> LanguageDetectionResult` function. The existing `detect_language(html) -> str` signature is preserved as a thin wrapper (`return detect_language_detailed(html).language`), so the current call site in `scheduler.py` keeps working with zero changes required.

**Rationale**: FR-L-010 requires the detection basis (declared vs. text, confidence, text volume) to be available to telemetry, and explicitly requires the primary call to remain usable without the caller consuming the extra detail. A wrapper function satisfies both: no caller is forced to change, but `scheduler.py`'s language-decision gate — which already opens a `safe_trace("language_detection", ...)` span and a `stage_log.timed("language_detection", ...)` block around this call (FR-T-002) — can be updated to call `detect_language_detailed` instead and attach the extra fields to the existing span/event, directly satisfying SC-007. This is a two-line change at the call site, not a redesign of it.

**Alternatives considered**: Changing `detect_language`'s signature directly to return the dataclass — rejected because it forces every caller (currently one, but the function is exported from `shared/tools/__init__.py` as public surface) to change simultaneously with the detection-logic change, mixing an interface change into a behavior fix and increasing the diff's blast radius for no benefit, given FR-L-010's own wording anticipates keeping the primary call simple.

---

## R8 — Fixture corpus sourcing

**Decision**: The FR-L-012 corpus is built from real, captured HTML snapshots of actual government portal pages (per the `/speckit-clarify` session), saved as static fixture files (e.g. under `tests/fixtures/language_detection/`), one or more per required case (13 languages untagged, 3+ out-of-set languages, boilerplate-heavy page, wrong/malformed `lang` attribute, too-short page, bilingual page).

**Rationale**: The project already has the tooling to capture this — the existing Playwright-based browser fetch path (`portal`/browser fetch used by the pipeline itself) can save a page's rendered HTML directly, so no new fetch mechanism is needed, only a one-time data-gathering pass. Saving static snapshots (rather than fetching live at test time) keeps the test suite deterministic and network-independent, consistent with how `tests/fixtures/resolution/` and `tests/fixtures/adjudication/` already store static JSON fixtures for this project's other stages.

**Alternatives considered**: Fetching live pages at test time — rejected as it would make the test suite flaky (site content changes, sites go down, network access required in CI) and violates the project's existing pattern of recorded-page fixtures for deterministic tests (per `plan.md` of spec 001, "Testing" row: "fixture-driven stage isolation, recorded-page fixtures for deterministic agent tests").

**Open action item carried into tasks**: identifying which 16+ real portal pages (13 languages + 3 out-of-set + edge cases) to capture, and capturing them, is a data-gathering task, not a code-writing task. It should be sequenced early in `tasks.md` since every accuracy-related test depends on it existing first.

---

## R9 — Dependency addition

**Decision**: Add `py3langid` to `pyproject.toml`'s `[project.dependencies]`, unpinned above a minimum tested version (mirroring the existing style, e.g. `py3langid>=0.2.2`; the actual latest published release is `0.3.0` — corrected during implementation after `2.2.0` proved not to exist on PyPI).

**Rationale**: Consistent with how `langsmith` was added for the 002 feature — a new runtime dependency for a well-scoped capability gap, added directly to the main dependency list (not `optional-dependencies`) since detection is not optional pipeline behavior.

**Alternatives considered**: Vendoring the library or its model data directly into the repo — rejected as unnecessary; the package has no heavyweight native build step (R1) so a normal `pip`-installed dependency carries none of the distribution complexity that would justify vendoring.

---

## Deferred (carried from spec, not resolved by research — resolved by corpus measurement during implementation)

- **FR-L-007 threshold and margin default values** — R2/R3 establish the *mechanism* (normalized probability threshold + top-2 margin); the specific numbers are set once the FR-L-012 corpus exists and can be measured against, not guessed here.
- **R4's 40-character minimum** is a starting point, subject to the same corpus-driven tuning.
