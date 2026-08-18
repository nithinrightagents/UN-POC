# Quickstart: EKAP AIQ Validation Guide

**Feature**: `specs/001-ekap-aiq-assessment` | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-13

How to prove the feature works, end to end. Scenarios are ordered by the spec's user story priorities, so each can be demonstrated independently and P1 needs no assessment pipeline running at all.

This is a validation guide. Implementation belongs in `tasks.md`.

## Prerequisites

- Python 3.11+
- A headless browser runtime installed (research R4)
- A GCP project with the Vertex AI API enabled, and `gcloud` installed (research R2)
- `.env` present — copy `.env.example` and set at minimum `AIQ_SUPPORTED_LANGUAGES` (ships empty by design), `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, and `AIQ_AGENT_MODELS`

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env

# GCP auth — Application Default Credentials, no key material in .env
gcloud auth application-default login
gcloud config set project "$GOOGLE_CLOUD_PROJECT"

aiq config show          # every parameter, effective value, default, source (FR-073)
aiq db init              # create the append-only schema
```

`aiq config show` must display **no credential material**. Authentication is ADC, deliberately outside the configuration set — the Configuration Snapshot is retained for audit and read back by anyone reconstructing a session, so anything in `.env` is effectively visible to every future auditor ([contracts/configuration.md](./contracts/configuration.md)).

Startup rejects the run if `AIQ_AGENT_MODELS` has a different length than `AIQ_ASSESSOR_AGENT_COUNT`, or if agents are identical on *every* divergence axis at once.

**The interim configuration runs all agents on one flash model**, so it needs `AIQ_ALLOW_IDENTICAL_AGENT_MODELS=true` and relies on temperature and prompt profile for divergence. That flag is recorded in the Configuration Snapshot, so any session run this way stays identifiable afterwards. Read Scenario 7's flag-rate gate with this in mind — it is the check this configuration is most likely to trip.

`aiq config show` should be the first thing run and the first thing checked in any bug report. Startup validation rejects an invalid configuration rather than warning ([contracts/configuration.md](./contracts/configuration.md)), so a clean `config show` means the run is at least well-formed.

---

## Scenario 1 — Review surface on seeded data (US1, P1)

**Proves**: SC-001, SC-004, SC-005 | **Needs no pipeline run.**

```bash
aiq seed demo-review --questions 5 --portal EE
aiq serve --port 8080
```

> **Since 005:** `aiq serve` now starts the combined admin/assessor/public app
> (`src/portal/webapp.py`); this review surface is mounted at `/review`, not
> `/`. Open `http://localhost:8080/review` (see
> [specs/005-un-ekap-platform/spec.md §2](../005-un-ekap-platform/spec.md)).

Open `http://localhost:8080/review`. For each seeded question verify the review surface shows, without navigating anywhere else: proposed answer, justification, numeric confidence **as a 0–100 percentage** (no tier label — FR-042), resolved URL, the source that supplied it, the region-scoped capture, and the referenced element with its text.

Then exercise all three dispositions:

| Action | Expected |
|---|---|
| Approve | Recorded human-approved with actor + timestamp; **system answer still retrievable** |
| Edit | Edited answer delivered; original preserved unchanged; edit attributed |
| Reject + override | Override delivered with reason; both answers in the audit trail |

Two negative checks that matter more than they look:

- One seeded question has **broken evidence**. Its confidence must be capped below the acceptance threshold, and the missing component must be named explicitly (FR-024).
- "Show detail" on any question must reveal **each individual agent's position** and the adjudication outcome (FR-048).

```bash
aiq audit reconstruct --session <session_id>   # full history from the session ID alone (SC-005)
```

---

## Scenario 2 — Independent draft answers (US2, P2)

**Proves**: SC-015, SC-017, SC-018, and the FR-011 independence property.

```bash
aiq run --portal EE --questions OSQ-1.1,OSQ-1.2 --agents 2 --no-adjudicate
```

Verify each agent produced a complete independent result, then run the check that actually matters:

```bash
aiq verify independence --session <session_id>
```

This asserts that **no agent's input contained any other agent's output** (FR-010) and that no validation invocation received more than one agent's output for the same pair (SC-017). It reads recorded inputs; it does not take the code's word for it.

Rejection check — must fail, and must fail loudly:

```bash
aiq run --portal EE --agents 1        # expect: rejected with a clear message (FR-009)
```

A silent fallback to a single agent here would be the worst possible failure: output that looks normal while the discrepancy signal is gone.

### Validation and verification

```bash
aiq verify evidence --session <session_id>
```

Confirms every output reaching adjudication had its evidence independently located at the cited URL and element reference and confirmed against the live page, with a verification timestamp (SC-018).

Fixture-driven cases (no network):

| Fixture | Expected |
|---|---|
| Element absent on a reachable page | Validation **fails**, discrepancy recorded as the gap (FR-087) |
| Element text mismatched | Validation **fails** with the specific mismatch |
| Target unreachable | **Not** an agent failure; deferred and re-attempted; escalates as unverifiable target if the bound exhausts (FR-088) |
| One agent fails repeatedly, others pass | Only the failing agent retried; pair escalates when validated count drops below 2 |

The third row is the one to check carefully — SC-020 requires zero cases where an unreachable target was recorded as a quality failure, and zero where an absent element was recorded as unreachable. They are separate facts about separate subjects.

---

## Scenario 3 — Discrepancy detection (US3, P3)

**Proves**: SC-013 | **No live assessment needed** — the Adjudicator is driven from fixed inputs.

```bash
aiq adjudicate --fixture tests/fixtures/adjudication/
```

| Fixture | Expected |
|---|---|
| Identical answers, delta ≤ threshold | No flag; consensus produced |
| Answers differ | Flagged regardless of confidence |
| Identical answers, delta > threshold | **Flagged** — agreement on the answer alone is not enough |
| Retry converges | Consensus produced; full retry history retained |
| Retry exhausted | Escalated with every position from every round; **no** automatic consensus |

Portal-level:

```bash
aiq adjudicate portal --fixture tests/fixtures/portal-level/
```

The two fixtures worth naming, because they are the ones that were wrong in an earlier draft of the spec:

- **50/50 affirmative, 40% differing** — affirmative-rate gap is exactly zero; must still flag on the differing-answer rate (FR-036).
- **Heavy first-round disagreement, full convergence on retry** — must still flag, because measures are taken on first-round positions, and **zero already-consensus questions may be re-run or discarded** (FR-039).

---

## Scenario 4 — URL resolution (US4, P4)

```bash
for mode in msq_first historical_first search_first; do
  AIQ_URL_RESOLUTION_MODE=$mode aiq resolve --fixture tests/fixtures/resolution/
done
```

Verify per mode: consultation order matches the mode; a later source is consulted **only** after every earlier one failed; search candidates are restricted to government TLDs; provenance records every source consulted, what each returned, and why any candidate was rejected.

No usable URL anywhere → questions recorded `unassessable` with resolution history, routed to escalation, **no speculative answer** (FR-007).

### Language decisions

```bash
aiq run --portal <out-of-set-language-portal> --agents 2
```

- A decision is raised naming the detected language and offering best-effort — not a silent skip, not a silent attempt (FR-017).
- **The rest of the batch keeps running** while it is pending (FR-020). Check that units for other portals continue to progress.
- Authorized → answers marked best-effort, confidence capped at the ceiling, original-language element text retained alongside any translation.
- Declined or window expired → escalated with the language as the reason, and the manner of resolution recorded.

---

## Scenario 5 — Custom questions (US5, P5)

```bash
aiq question add --cycle 2026 --text "Does the portal offer a native mobile app?" --type binary
```

Verify: flagged custom, attributed, cycle-scoped; assessed by the same agent count and adjudicated by the same rules; **added mid-run without re-assessing or invalidating completed work** (FR-056); absent from the next cycle's questionnaire unless re-added (FR-057).

---

## Scenario 6 — Resumability (SC-006)

The one scenario that must be run by actually killing the process. A graceful shutdown path would not exercise what FR-066 protects against.

```bash
aiq run --cycle 2026 --batch-size 50 &
sleep 45 && kill -9 %1          # hard kill mid-round
aiq run --cycle 2026 --resume
```

Verify:

- Zero duplicated units, zero lost units.
- Agents that reached a **terminal** state were retained and **not** re-run (FR-067a).
- Agents caught mid-run or mid-validation were **discarded and re-run from scratch** (FR-067b).
- No discarded partial output reached adjudication.

```bash
aiq verify resume --session <session_id>
```

The subtle case to seed deliberately: an agent interrupted **mid-validation-retry**. It has a completed assessment but incomplete validation, so the whole run is non-terminal and must be discarded (research R8). Retaining the assessment and re-running only validation is the plausible-looking wrong behaviour.

---

## Scenario 7 — Benchmark mode (SC-002, SC-021, SC-022)

```bash
aiq benchmark load --set tests/fixtures/benchmark/labelled-set.json
aiq benchmark run --set labelled-set --agents 2
aiq benchmark report --session <session_id>
```

Report must contain overall consensus accuracy, accuracy by question class and by numeric confidence band, per-question discrepancy flag rate, portal-level measures, and escalation counts by reason (FR-096).

Gates:

- **Overall accuracy ≥ 80%**, pooled, measured **before any human review** (SC-002, FR-097). Breakdowns are reported, not gated.
- **Discrepancy flag rate within the configured band (default 5–25%)**. A rate **at or below** the 5% floor is a **failure** indicating the agents are not independent — not a success (SC-003). This inverts the usual reading of an agreement metric and is the check most likely to be misinterpreted by whoever reads the report next.

> **Expect pressure on the floor under the interim configuration.** With every agent on the same flash model, divergence comes only from temperature and prompt profile, so a sub-floor flag rate is a plausible first result. If it happens, that is the configuration failing — not the pipeline. The fix is a one-line config change moving one agent to a different model tier (FR-074, no code edit), then re-running `aiq benchmark compare` against the first run to see the effect attributably (SC-022).

Contamination check:

```bash
aiq verify benchmark-isolation --session <session_id>
```

Asserts ground truth reached zero agent, Validator, or Adjudicator invocations, and zero benchmark answers appear in any cycle's delivered results (SC-021).

Run comparison:

```bash
aiq benchmark compare --run <a> --run <b>    # per-measure delta + configuration diff (SC-022)
```

---

## Scenario 8 — Authentication-gated content (SC-024)

```bash
aiq run --portal <portal-with-login-gated-feature> --questions <gated-question>
```

- No answer produced from publicly reachable pages.
- Pair escalates as `requires_authenticated_access`, recorded **distinctly** from an unreachable target.
- A question carrying the FR-107 attribute never reaches an agent at all.

```bash
aiq verify no-credentials      # asserts zero portal credentials stored anywhere (FR-110)
```

---

## Scenario 9 — Export (SC-023)

```bash
aiq export --cycle 2026 --out ./out/
```

Verify record count equals the cycle's delivered-answer count; zero awaiting-review, zero unresolved escalations, zero benchmark answers; every excluded question in the exclusion report with a reason; every record resolves back to its session ID and evidence artifacts.

---

## Scenario 10 — Observability, rate limits, accessibility

```bash
aiq telemetry summary --session <session_id>   # units by state, escalations by reason, failures by stage
aiq telemetry timings --session <session_id>   # per-stage + end-to-end durations (SC-011 input)
aiq telemetry fetches --session <session_id>   # per-domain, split assessor vs validator (SC-012, SC-019)
aiq telemetry cost --session <session_id>      # by stage and agent (FR-116)
```

Rate-limit conformance must be **demonstrated from the fetch log**, not asserted (SC-012). The assessor/validator split must show both callers drawing from **one** shared per-domain budget (SC-019).

```bash
aiq verify telemetry-hygiene --session <session_id>   # zero credentials, zero ground truth (FR-117)
```

Accessibility (SC-026):

```bash
npm run a11y          # WCAG 2.1 AA audit over the review surface
```

Zero unresolved Level A or AA failures. Manually confirm evidence text is presented in the portal's original language with any translation shown **alongside** it, never in place of it (FR-120).

---

## Full test suite

```bash
pytest                          # everything
pytest tests/independence/      # the assertions that make the method defensible
pytest tests/unit/domain/       # state machine + resume, no browser/model/network needed
```

`tests/independence/` is called out separately because it is the suite whose failure invalidates results rather than merely reporting a bug. A run whose independence assertions fail has produced numbers that look fine and mean nothing.

## Known gate that cannot yet pass

**SC-011** has no agreed target — the spec's Open Question 5. `aiq telemetry timings` produces the measurement, but until the cycle assessment window is agreed there is nothing to compare it against, so SC-011 can be measured and reported but not passed or failed.
