# Contract: Configuration Additions

**Satisfies**: FR-L-007, FR-L-008 | **Source**: `.env`, read at process start (consistent with spec 001, FR-072–FR-075)

This feature adds three new operational parameters to the existing `Settings` object (`shared/config/settings.py`). It does not modify or remove any parameter from spec 001's [configuration contract](../../001-ekap-aiq-assessment/contracts/configuration.md), including `AIQ_SUPPORTED_LANGUAGES` and `AIQ_LANGUAGE_DECISION_WINDOW_HOURS`, which this feature reads but does not alter.

## New parameters

| Env var | Type | Default | Validation | Req |
|---|---|---|---|---|
| `AIQ_LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD` | float | `0.60`† | 0.0–1.0 | FR-L-007 |
| `AIQ_LANGUAGE_DETECTION_MARGIN_THRESHOLD` | float | `0.05`† | 0.0–1.0 | FR-L-007 |
| `AIQ_LANGUAGE_DETECTION_MIN_TEXT_CHARS` | int | `40`† | ≥ 1 | FR-L-008 |

† **Kept as shipped after T029's corpus-sweep review.** These started as placeholders (per the spec's Deferred Design Decisions and [research.md](../research.md) R4), to be checked against the FR-L-012 real-page fixture corpus once it existed rather than guessed permanently. That review (22-fixture corpus, `tests/fixtures/language_detection/`) found every real-content fixture classifies at ~1.0 normalized confidence regardless of page length (the shortest real fixture, 140 characters, still scored 1.0) — so `0.60` has wide headroom and correctly separates genuine content from noise without being tuned tighter. It also found the margin threshold is rarely the deciding factor against real text (see the note below) — no fixture's outcome changed under any tested adjustment, so all three values ship unchanged. They remain configurable specifically so future tuning doesn't require a code change (mirrors spec 001's own posture on `AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD` and similar tunables).

**Note on the margin threshold's real-world impact**: `py3langid`'s `norm_probs=True` output was found to be extremely peaked on real, coherent prose during fixture construction — every attempt at a genuinely balanced mixed-language sample (French/English, Spanish/Portuguese, Malay/Indonesian, Croatian/Bosnian, at lengths from ~30 to ~2500 characters) still resolved with the top candidate at 57%-100% confidence, never producing a top-2 gap below `0.05`. In practice, `AIQ_LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD` and `AIQ_LANGUAGE_DETECTION_MIN_TEXT_CHARS` carry nearly all of the "don't guess" burden against realistic portal pages; the margin check is a defensive branch for pathological inputs rather than a lever that fires often. See `tests/fixtures/language_detection/README.md` for the full detail and `test_language_detection.py`'s `test_narrow_top_two_margin_returns_unknown` for how the branch is verified directly (mocked classifier output) instead of via a corpus fixture.

### Notes on specific defaults

- **`AIQ_LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD = 0.60`** is a conservative starting point: below it, the detector prefers to say `unknown` and let a human decide, rather than assert a language it isn't confident about. This mirrors the project's existing bias — spec 001's `AIQ_SUPPORTED_LANGUAGES` defaults to empty specifically so an uncertain state routes to a human rather than asserting untested coverage (spec 001, [configuration.md](../../001-ekap-aiq-assessment/contracts/configuration.md) notes).
- **`AIQ_LANGUAGE_DETECTION_MARGIN_THRESHOLD = 0.05`** means the top two candidates must differ by at least 5 percentage points of normalized probability, or the result is `unknown` (research R3). A genuinely bilingual page (e.g. `fr: 0.51, en: 0.48`) falls below this margin and correctly returns `unknown`.
- **`AIQ_LANGUAGE_DETECTION_MIN_TEXT_CHARS = 40`** is roughly one short sentence. Pages with less extracted visible text than this never reach the classifier (research R4).

## Startup validation (additive)

No new startup-rejection rules are introduced beyond the existing numeric-range checks each new parameter carries in the table above (consistent with spec 001's validation posture — out-of-range values are rejected at startup, not silently clamped).

## Inspection interface

These three parameters appear in `aiq config show` output (spec 001, FR-073) alongside every other parameter, with no special-casing required — the existing inspection interface already enumerates every field on `Settings`.

## Snapshot semantics

Captured into the Configuration Snapshot at session start like every other parameter (spec 001, FR-075). A retry reads the snapshot value, not live configuration — consistent with every other tunable.
