# Quickstart: Multi-Language Detection for Portal Pages

**Feature Directory**: `specs/003-multi-language-detection`
**Spec**: [spec.md](./spec.md) | **Data model**: [data-model.md](./data-model.md) | **Contracts**: [contracts/](./contracts/)

Validation scenarios below map directly to the User Scenarios in spec.md, ordered so each can be demonstrated independently once `tests/fixtures/language_detection/` exists (research R8).

## Prerequisites

```bash
# From repo root, with the project's virtualenv active
pip install -e ".[dev]"          # picks up the new py3langid dependency once added to pyproject.toml
```

No network access, no GCP credentials, and no browser (Playwright) are required to run these scenarios — detection is pure in-process logic (FR-L-009), and the fixture corpus is static saved HTML (research R8), not live-fetched.

## Scenario 1 — Untagged German page is detected correctly (the core bug fix)

```bash
pytest tests/unit/test_language_detection.py -k "german_untagged" -v
```

**Expected**: `detect_language(html)` on the German fixture (no `<html lang>` attribute) returns `"de"`, not `"en"`. This is the single most important regression check — it is the exact bug the spec opens with.

## Scenario 2 — Out-of-set language is reported specifically, not collapsed

```bash
pytest tests/unit/test_language_detection.py -k "out_of_set" -v
```

**Expected**: the Turkish (or other out-of-set) fixture returns `"tr"`, not `"en"` and not `"unknown"`. Then, at the gate level:

```bash
pytest tests/unit/test_modular_structure.py tests/integration -k "language" -v
```

**Expected**: `language_requires_decision("tr", settings.supported_languages)` is `True`, and a pending `LanguageDecision` is created naming `tr` — unchanged gate behavior (FR-L-013), now fed a correct code.

## Scenario 3 — Boilerplate does not decide the page's language

```bash
pytest tests/unit/test_language_detection.py -k "boilerplate" -v
```

**Expected**: a Dutch fixture with English nav/footer/cookie-banner text still returns `"nl"` — the fixture is specifically constructed (from a real captured page, per R8) so that a naive "classify the whole page" approach would return `"en"` and this test would catch that regression.

## Scenario 4 — Undetectable page returns `unknown`, never a guess

```bash
pytest tests/unit/test_language_detection.py -k "too_short or ambiguous" -v
```

**Expected**: both the too-short fixture and the deliberately bilingual (French/English) fixture return `"unknown"`. Confirm via `detect_language_detailed()` that `source` is `"undetermined"` for the too-short case and `"text_analysis"` for the bilingual case (the margin check fired, not the length check) — the distinction matters for SC-007.

## Scenario 5 — Declared attribute still wins, and is validated

```bash
pytest tests/unit/test_language_detection.py -k "declared_attribute" -v
```

**Expected**:
- `<html lang="ko">` with Korean content → `"ko"`, `source="declared_attribute"`, text analysis not invoked (verify via a call-count assertion on the classifier, or a monkeypatch, so this test would fail if someone accidentally always runs text analysis).
- `<html lang="">` or `<html lang="default">` with Italian content → falls through to text analysis → `"it"`, `source="text_analysis"`.

## Scenario 6 — Full corpus accuracy sweep (SC-001, SC-002, SC-003)

```bash
pytest tests/unit/test_language_detection.py -k "corpus_sweep" -v
```

**Expected**: iterates every fixture under `tests/fixtures/language_detection/`, asserts `detect_language(html) == expected_language` (or `"unknown"` for the deliberately unclassifiable cases) for each. This single test is the executable form of SC-001–SC-003: 100% of the 13 configured languages correctly identified, ≥90% of out-of-set languages correctly named, zero incorrect English classifications.

## Scenario 7 — Hot path budget (SC-005)

```bash
pytest tests/unit/test_language_detection.py -k "performance" -v
```

**Expected**: timing assertion over the corpus (warm classifier, i.e. not counting first-import model load) shows p95 per-call latency under 100ms, and a mock/patch on the HTTP client and any model-call surface confirms zero calls made during detection.

## Scenario 8 — Existing gate suite is untouched (SC-008, FR-L-013)

```bash
pytest tests/unit tests/contract tests/integration -v
```

**Expected**: full existing suite passes unmodified, including `tests/unit/test_modular_structure.py` and any language-decision-gate-adjacent tests already in the repo. No test file outside the new `test_language_detection.py` and the fixture directory should need to change.

## Manual smoke check (optional)

```bash
python -c "
from shared.tools.language import detect_language, detect_language_detailed
html = '<html><body><p>Willkommen auf unserer offiziellen Regierungsseite.</p></body></html>'
print(detect_language(html))              # expect: de
print(detect_language_detailed(html))     # expect: LanguageDetectionResult(language='de', source='text_analysis', confidence=..., text_length=...)
"
```

## Not covered by this quickstart

- Building the `tests/fixtures/language_detection/` corpus itself — that is a data-gathering task (research R8), tracked in `tasks.md`, and is a prerequisite for every scenario above except the manual smoke check.
- Tuning the three threshold defaults in [contracts/configuration.md](./contracts/configuration.md) against real corpus results — also a `tasks.md` item, not a quickstart validation step.
