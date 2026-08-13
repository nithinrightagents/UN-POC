# Tasks: EKAP AIQ — AI-Assisted Portal Assessment

**Feature Directory**: `specs/001-ekap-aiq-assessment`
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Data model**: [data-model.md](./data-model.md)
**Generated**: 2026-08-13

**Stack**: Python 3.11+, ADK, Vertex AI (GCP auth), SQLite (PoC) → SQL Server, headless browser, `asyncio`, pytest
**PoC scope**: Module 2.1 Institutional Framework — 26 question records, 5 countries ([poc-question-set.md](./poc-question-set.md))

## Conventions

- `- [ ] [TaskID] [P?] [Story?] Description with file path`
- **[P]** = parallelizable (different file, no incomplete dependency)
- **[US#]** = user story from spec.md. Setup, Foundational, and cross-cutting phases carry no story label.
- Paths are relative to repo root and follow [plan.md](./plan.md) §Project Structure.

**On tests**: the spec did not ask for TDD, so tests are not generated wholesale. Three suites are included because the design documents make them load-bearing rather than optional — `tests/independence/` (its failure invalidates results rather than reporting a bug), `tests/unit/domain/` (pure logic, no I/O — the resume and confidence rules are unreachable by manual testing), and `tests/contract/` (the closed agent schemas are how FR-010 is enforced). Everything else is verified through the `aiq verify …` commands, which are product features under FR-112–FR-118, not test scaffolding.

---

## Phase 1: Setup

- [X] T001 Create the directory tree exactly as specified in [plan.md](./plan.md) §Project Structure, with `__init__.py` in every package under `src/ekap_aiq/`
- [X] T002 Create `pyproject.toml` declaring Python ≥3.11, ADK, google-genai, a headless browser driver, SQLAlchemy, pydantic, pytest, and the `aiq` console entry point
- [X] T003 [P] Create `.env.example` listing every parameter from [contracts/configuration.md](./contracts/configuration.md) with its default, and no credential values
- [X] T004 [P] Configure ruff and formatting in `pyproject.toml`
- [X] T005 [P] Configure pytest markers (`unit`, `contract`, `integration`, `independence`) in `pyproject.toml`
- [X] T006 [P] Write `README.md` covering GCP auth setup (`gcloud auth application-default login`), install, and the `aiq` command list
- [X] T007 Create the CLI skeleton in `src/ekap_aiq/cli.py` with subcommands `run`, `resume`, `config`, `export`, `benchmark`, `serve`, `verify`, `db`
- [X] T008 [P] Load the 26 PoC question records into `data/questions/module_2_1.json`, expanding rows 12 and 13 into their six sector variants, each carrying its indicator ID, `answer_type: binary`, `evidence_locus`, and `requires_authenticated_access: false` per [poc-question-set.md](./poc-question-set.md)

---

## Phase 2: Foundational

**Blocking — every user story depends on this phase.**

### Configuration

- [X] T009 Implement the typed settings object in `src/ekap_aiq/config/settings.py` covering all parameters in [contracts/configuration.md](./contracts/configuration.md) (FR-072)
- [X] T010 Implement startup validation in `src/ekap_aiq/config/validation.py`: reject agent count < 2, best-effort ceiling ≥ acceptance threshold, out-of-range thresholds, unknown resolution mode, model-list length mismatch, and identical models without the explicit override (FR-009, FR-018, FR-134)
- [X] T011 Implement `aiq config show` in `src/ekap_aiq/cli.py` printing every parameter with effective value, default, and source (FR-073)
- [X] T012 Implement per-session configuration snapshotting in `src/ekap_aiq/config/snapshot.py`; retries read the snapshot, never live config (FR-063, FR-075)

### Domain (pure logic, no I/O)

- [X] T013 [P] Define all 20 entities as dataclasses in `src/ekap_aiq/domain/entities.py` per [data-model.md](./data-model.md)
- [X] T014 [P] Implement the unit state machine in `src/ekap_aiq/domain/unit_state.py` with exactly three terminal states — `delivered`, `escalated`, `unassessable` (FR-065)
- [X] T015 Implement `remaining_work(unit_state, agent_run_states)` in `src/ekap_aiq/domain/resume.py`: retain terminal agent runs, discard non-terminal ones including mid-validation-retry (FR-067a, FR-067b)
- [X] T016 [P] Implement the confidence acceptance rules in `src/ekap_aiq/domain/confidence.py` — threshold comparison, evidence-missing cap, best-effort ceiling; no tier labels (FR-024, FR-041, FR-134)
- [X] T017 [P] Implement portal agreement measures in `src/ekap_aiq/domain/measures.py` — differing-answer rate and affirmative-rate gap over first-round positions, plus the FR-058 eligibility predicate (FR-035–FR-037)
- [X] T018 [P] Unit-test the state machine's terminal exhaustiveness in `tests/unit/domain/test_unit_state.py` — assert no path leaves the machine without a delivered answer or a recorded reason (SC-009)
- [X] T019 [P] Unit-test resume semantics in `tests/unit/domain/test_resume.py`, including the mid-validation-retry case that must be discarded and re-run whole (FR-067b)
- [X] T020 [P] Unit-test measures in `tests/unit/domain/test_measures.py` with the 50/50-affirmative, 40%-differing fixture that must flag on differing-answer rate alone (FR-036)

### Persistence

- [X] T021 Define the append-only schema in `src/ekap_aiq/persistence/schema.py` for all entities and telemetry records
- [X] T022 Implement repositories in `src/ekap_aiq/persistence/repositories.py` exposing insert and read only — no update or delete path anywhere (FR-062)
- [X] T023 Implement the isolated `src/ekap_aiq/persistence/benchmark_repo.py` with no import path from `agents/`, so ground-truth leakage is an import error (FR-094)
- [X] T024 Implement `aiq db init` in `src/ekap_aiq/cli.py`

### Shared infrastructure

- [X] T025 Implement the per-domain token bucket in `src/ekap_aiq/ratelimit/token_bucket.py` as a single shared instance serving both assessor and validator callers (FR-069, FR-089)
- [X] T026 Record every acquisition with `caller_class` and limiter wait time in `src/ekap_aiq/telemetry/fetch_log.py` (FR-115)
- [X] T027 Implement the Vertex AI provider port in `src/ekap_aiq/agents/provider.py` — GCP auth via ADC, per-agent model/temperature/prompt-profile binding, model identity returned per invocation (research R2, R7)
- [X] T028 Implement the cost ledger in `src/ekap_aiq/telemetry/cost_ledger.py`, attributing invocations to stage and agent index (FR-116)
- [X] T029 [P] Implement stage-transition events with start and end timestamps in `src/ekap_aiq/telemetry/stage_events.py` (FR-113, FR-114)
- [X] T030 [P] Enforce telemetry hygiene in `src/ekap_aiq/telemetry/hygiene.py` — no credentials, no ground truth, and no import path from `telemetry/` into `agents/` (FR-117, FR-118)

### Portal traversal

- [X] T031 Implement headless browser page acquisition in `src/ekap_aiq/portal/browser.py`, acquiring from the shared limiter before every fetch (research R4)
- [X] T032 Implement region-scoped visual capture in `src/ekap_aiq/portal/capture.py` (FR-021)
- [X] T033 Implement the composite durable element reference in `src/ekap_aiq/portal/element_ref.py` — CSS path, normalized text hash, sibling index — with resolution that falls back from selector to text-hash search (research R5)
- [X] T034 [P] Implement primary-language detection in `src/ekap_aiq/portal/language.py` (FR-015)
- [X] T035 [P] Implement interstitial, challenge-page, and authentication-boundary detection in `src/ekap_aiq/portal/boundaries.py` using the three signals in research R9 (FR-071, FR-108)

---

## Phase 3: User Story 1 — Assessor reviews a pre-filled answer (P1) 🎯 MVP

**Goal**: A human can open a question, see a complete self-contained evidence set, and approve, edit, or reject-and-override it — with every action attributed and timestamped.

**Independent test**: Seed one pre-computed assessment with complete evidence. Verify the review surface renders answer, justification, numeric confidence, and all three evidence components; that all three dispositions persist correctly; and that each record carries actor identity and timestamp. **No assessment pipeline needs to run.**

- [X] T036 [P] [US1] Implement the Assessor Decision record and its append-only repository in `src/ekap_aiq/persistence/repositories.py` (FR-045, FR-052)
- [X] T037 [US1] Implement `aiq seed demo-review` in `src/ekap_aiq/cli.py`, seeding assessments with complete evidence plus one with deliberately broken evidence
- [X] T038 [US1] Implement the review API in `src/ekap_aiq/review/api.py` returning answer, justification, numeric confidence, resolved URL, supplying source, and the full evidence set for a question (FR-043)
- [X] T039 [US1] Implement per-portal review unlocking in `src/ekap_aiq/review/unlock.py` — a portal becomes reviewable only when every question reaches a terminal state; escalated questions appear in-set marked as such (FR-043a, FR-043b)
- [X] T040 [US1] Implement approve, edit, and reject-and-override handlers in `src/ekap_aiq/review/actions.py`, preserving the system-proposed answer unchanged and requiring a reason on override (FR-044, FR-046, FR-047)
- [X] T041 [US1] Implement the review web surface in `src/ekap_aiq/review/web/`, displaying confidence as a 0–100 percentage with no tier label (FR-042)
- [X] T042 [P] [US1] Render the evidence viewer in `src/ekap_aiq/review/web/evidence.py` — capture, element reference, and element text shown inline without leaving the surface (FR-023)
- [X] T043 [P] [US1] Display the per-agent breakdown — each agent's position and the adjudication outcome — behind a detail affordance in `src/ekap_aiq/review/web/detail.py` (FR-048)
- [X] T044 [US1] Mark answers with missing or unresolvable evidence, capping confidence below the acceptance threshold and naming the missing component in `src/ekap_aiq/review/api.py` (FR-024)
- [X] T045 [US1] Implement `aiq serve` in `src/ekap_aiq/cli.py`
- [X] T046 [US1] Implement `aiq audit reconstruct --session <id>` in `src/ekap_aiq/review/audit.py`, rebuilding full history from the session identifier alone (FR-061, SC-005)

**Checkpoint**: US1 is independently demonstrable — Scenario 1 of [quickstart.md](./quickstart.md) passes end to end.

---

## Phase 4: User Story 2 — System produces independent draft answers (P2)

**Goal**: N ≥ 2 mutually independent Assessor Agents evaluate each question, each output passes a confidence gate, and each is independently validated against the live page.

**Independent test**: Run the configured agent set against a fixed portal and question set with no adjudication. Verify each agent produced a complete independent result, that no agent's input contained another's output, and that the population shows non-degenerate spread.

### Agent contracts and independence

- [X] T047 [P] [US2] Implement the closed Assessor Agent input schema in `src/ekap_aiq/agents/schemas.py` with no field able to carry another agent's output (FR-010, [contracts/assessor-agent.md](./contracts/assessor-agent.md))
- [X] T048 [P] [US2] Implement the Assessor Agent output schema with answer, confidence, justification, evidence, auth-boundary fields, and model identity in `src/ekap_aiq/agents/schemas.py`
- [X] T049 [US2] Implement the Assessor Agent in `src/ekap_aiq/agents/assessor.py`, one ADK session per run with no shared conversational state (FR-008, research R7)
- [X] T050 [P] [US2] Author the versioned prompt profiles in `src/ekap_aiq/agents/prompts/` — `literal` and `inferential` as two defensible evaluative stances, not two phrasings of one (research R7)
- [X] T051 [US2] Enforce that confidence is recorded before any cross-agent comparison and derives only from this agent's observed evidence in `src/ekap_aiq/agents/assessor.py` (FR-013)
- [X] T052 [US2] Return no answer and record the boundary URL when an authentication boundary is detected in `src/ekap_aiq/agents/assessor.py` (FR-108, invariant A5)
- [X] T053 [P] [US2] Contract-test the closed input schema in `tests/contract/test_assessor_input.py` — assert a foreign agent's output cannot be represented in it (FR-010)
- [X] T054 [P] [US2] Implement `aiq verify independence --session <id>` in `src/ekap_aiq/agents/verify.py`, reading recorded inputs to assert no cross-agent contamination (SC-017)
- [X] T055 [P] [US2] Write the independence suite in `tests/independence/test_agent_isolation.py` asserting session isolation and non-degenerate answer/confidence spread (SC-008)

### Confidence gate

- [X] T056 [US2] Implement the confidence gate in `src/ekap_aiq/agents/confidence_gate.py`, applied after the agent completes and **before** validation so a doomed output does not consume a validator fetch (FR-134)
- [X] T057 [US2] Issue the confidence-retry addendum directing the agent to seek better or more authoritative evidence, never to report a higher number in `src/ekap_aiq/agents/confidence_gate.py` (FR-136)
- [X] T058 [US2] Track the confidence retry counter independently of the validation and adjudication counters in `src/ekap_aiq/agents/confidence_gate.py` (FR-137)
- [X] T059 [US2] Admit a still-below-threshold output unchanged and deliver it marked low confidence rather than escalating in `src/ekap_aiq/agents/confidence_gate.py` (FR-138, FR-139)

### Validator

- [X] T060 [US2] Implement the Validator in `src/ekap_aiq/agents/validator.py`, receiving exactly one agent output per invocation (FR-076, FR-079)
- [X] T061 [US2] Implement the five quality checks and the numeric quality score with specific gaps in `src/ekap_aiq/agents/validator.py` (FR-077, FR-078)
- [X] T062 [US2] Implement independent live re-traversal of the cited link and element resolution in `src/ekap_aiq/agents/verification.py` (FR-086)
- [X] T063 [US2] Implement the verification outcome taxonomy — `confirmed`, `element_absent`, `text_mismatch`, `target_unreachable` — keeping unreachable targets attributed separately from quality failures in `src/ekap_aiq/agents/verification.py` (FR-087, FR-088, SC-020)
- [X] T064 [US2] Stamp `verified_at` on confirmed verification only, since it is the sole discriminator between FR-025 and FR-087 in `src/ekap_aiq/agents/verification.py` (FR-091)
- [X] T065 [US2] Route validator fetches through the shared per-domain limiter with `caller_class="validator"` in `src/ekap_aiq/agents/verification.py` (FR-089, SC-019)
- [X] T066 [US2] Implement the per-agent validation retry loop with a maximum of two retries, supplying gaps as an addendum and re-running only the failing agent in `src/ekap_aiq/orchestration/retry_loops.py` (FR-080, FR-081, FR-084)
- [X] T067 [US2] Escalate the pair when fewer than two validated outputs remain after the retry limit in `src/ekap_aiq/orchestration/retry_loops.py` (FR-082, SC-016)
- [X] T068 [P] [US2] Implement `aiq verify evidence --session <id>` confirming every adjudicated answer carried live-verified evidence in `src/ekap_aiq/agents/verify.py` (SC-018)

**Checkpoint**: US1 + US2 deliver evidence-backed, validated draft answers ready for a human.

---

## Phase 5: User Story 3 — Disagreements are detected and resolved (P3)

**Goal**: Validated positions are compared into a consensus answer; disagreement retries with an anonymised addendum, then escalates rather than manufacturing false consensus.

**Independent test**: Feed the Adjudicator fixed pre-computed result sets covering agreement, answer disagreement, confidence-only disagreement, retry convergence, and retry exhaustion. Verify each outcome with no live assessment running.

- [X] T069 [US3] Implement per-question adjudication in `src/ekap_aiq/agents/adjudicator.py`, invoked only when all agents are terminal and at least two validated positions exist (FR-027, FR-082)
- [X] T070 [US3] Implement the discrepancy decision table — answers differ, or max pairwise confidence delta above threshold in `src/ekap_aiq/agents/adjudicator.py` (FR-028, FR-029)
- [X] T071 [US3] Implement the adjudication retry loop with an anonymised disagreement addendum that attributes no position to an identified agent in `src/ekap_aiq/orchestration/retry_loops.py` (FR-030, FR-031, FR-032)
- [X] T072 [US3] Escalate on persistent disagreement carrying every agent's position from every round in `src/ekap_aiq/orchestration/retry_loops.py` (FR-033)
- [X] T073 [US3] Compute consensus confidence separately, never altering per-agent values in `src/ekap_aiq/agents/adjudicator.py` (FR-034)
- [X] T074 [P] [US3] Implement portal-level adjudication over first-round positions in `src/ekap_aiq/agents/portal_adjudicator.py` (FR-035, FR-038, FR-039)
- [X] T075 [P] [US3] Implement the escalation queue with single-disposition concurrency control via a conditional write on `disposition IS NULL` in `src/ekap_aiq/persistence/repositories.py` (FR-049)
- [X] T076 [P] [US3] Build the escalation queue and portal-level case views in `src/ekap_aiq/review/escalations.py` showing both measures, thresholds in force, and the per-question breakdown (FR-050)
- [X] T077 [P] [US3] Create adjudication fixtures in `tests/fixtures/adjudication/` covering all five cases and `tests/fixtures/portal-level/` covering the zero-gap and retry-convergence cases

**Checkpoint**: the full assess → validate → adjudicate → review path runs end to end.

---

## Phase 6: User Story 4 — Links are resolved from prioritized sources (P4)

**Goal**: Resolve a link for every question–portal pair through prior-survey KB → MSQ → internet search, then **traverse it live** whichever source supplied it.

**Independent test**: Configure each of the three modes in turn against fixtures where each source succeeds, returns nothing, or returns an unusable candidate. Verify consultation order, short-circuit behaviour, and recorded provenance.

- [X] T078 [US4] Implement the ordered resolution chain with fall-through in `src/ekap_aiq/linkresolution/chain.py`, defaulting to `historical_first` (FR-001, FR-002, FR-003)
- [X] T079 [P] [US4] Implement the prior-survey KB link source in `src/ekap_aiq/linkresolution/sources/prior_survey_kb.py`, recording origin cycle and session and enforcing the maximum link age (FR-127, FR-128)
- [X] T080 [P] [US4] Implement the MSQ link source in `src/ekap_aiq/linkresolution/sources/msq.py` extracting **links only** — the module must expose no path returning a reported value as an answer (FR-126)
- [X] T081 [P] [US4] Implement gov-TLD-restricted search discovery in `src/ekap_aiq/linkresolution/sources/search.py` (FR-004)
- [X] T082 [US4] Implement the candidate usability test and rejection-reason recording in `src/ekap_aiq/linkresolution/usability.py` (FR-005)
- [X] T083 [US4] **Enforce live traversal of every resolved link before any answer is produced**, whatever source supplied it, in `src/ekap_aiq/linkresolution/chain.py` (FR-124, FR-125)
- [X] T084 [US4] Record full resolution provenance — every source consulted in order, what each returned, which supplied the link, and why candidates were rejected in `src/ekap_aiq/linkresolution/chain.py` (FR-006)
- [X] T085 [US4] Mark questions unassessable with resolution history and route to escalation when no source yields a usable link in `src/ekap_aiq/linkresolution/chain.py` (FR-007)
- [X] T086 [P] [US4] Implement the evidence-locus rule in `src/ekap_aiq/linkresolution/locus.py` — `national_portal_only` restricts evidence to the portal and its subdomains; `any_government_domain` permits gov-TLD traversal beyond it (FR-129–FR-131)
- [X] T087 [US4] Apply per-domain rate limits and access policies to **every** domain visited, not only the portal domain in `src/ekap_aiq/portal/browser.py` and `src/ekap_aiq/ratelimit/token_bucket.py` (FR-132)
- [X] T088 [P] [US4] Implement the language decision flow in `src/ekap_aiq/orchestration/language_decision.py` — raise a human decision for out-of-set languages, cap confidence on authorized best-effort, escalate on decline or expiry, and never block the rest of the batch (FR-016–FR-020)
- [X] T089 [P] [US4] Create resolution fixtures in `tests/fixtures/resolution/` covering success, empty, and unusable-candidate cases per source

### Orchestration

- [X] T090 [US4] Implement the batch scheduler in `src/ekap_aiq/orchestration/scheduler.py` with `asyncio.TaskGroup`, bounding concurrency per unit rather than per fetch (research R6)
- [X] T091 [US4] Implement `aiq run` and `aiq resume` in `src/ekap_aiq/cli.py`, deriving remaining work from recorded state via `domain/resume.py` (FR-064–FR-066)
- [X] T092 [US4] Implement `aiq verify resume --session <id>` asserting zero duplicated and zero lost units in `src/ekap_aiq/orchestration/verify.py` (SC-006)

**Checkpoint**: a real end-to-end run against the 5 PoC countries is possible.

---

## Phase 7: User Story 5 — Assessors extend the questionnaire (P5)

**Goal**: An ad-hoc question flows through the same pipeline as a standard one, scoped to the active cycle.

**Independent test**: Add a custom question mid-run and verify it is marked custom, cycle-scoped, assessed by the same agent set, adjudicated by the same rules, and does not invalidate completed work.

- [X] T093 [P] [US5] Implement `aiq question add` in `src/ekap_aiq/cli.py`, persisting the question flagged custom, attributed, and cycle-scoped (FR-053, FR-054)
- [X] T094 [US5] Enqueue a mid-run custom question against in-scope portals without re-assessing or invalidating completed work in `src/ekap_aiq/orchestration/scheduler.py` (FR-056)
- [X] T095 [P] [US5] Exclude prior-cycle custom questions from a new cycle's questionnaire assembly in `src/ekap_aiq/domain/cycle.py` (FR-057)
- [X] T096 [US5] Apply the FR-058 eligibility predicate so partially-covered custom questions do not skew portal measures in `src/ekap_aiq/domain/measures.py` (FR-058)

---

## Phase 8: Benchmark evaluation

**Cross-cutting — makes SC-002, SC-003, and SC-008 verifiable.**

- [X] T097 Implement benchmark set storage in `src/ekap_aiq/benchmark/store.py` with label source and assigning actor (FR-092)
- [X] T098 Implement benchmark mode in `src/ekap_aiq/benchmark/runner.py` driving the **same** pipeline as production, with sessions marked and answers never delivered into a cycle (FR-093, FR-095)
- [X] T099 Implement the measures report in `src/ekap_aiq/benchmark/measures.py` — overall accuracy, accuracy by question class and by numeric confidence band, discrepancy flag rate, portal measures, escalations by reason (FR-096)
- [X] T100 Compute accuracy on the consensus answer before any human review in `src/ekap_aiq/benchmark/measures.py` (FR-097)
- [X] T101 [P] Implement `aiq benchmark compare --run a --run b` reporting per-measure deltas and the configuration difference in `src/ekap_aiq/benchmark/compare.py` (FR-099, SC-022)
- [X] T102 [P] Implement `aiq verify benchmark-isolation --session <id>` asserting ground truth reached zero agent, validator, or adjudicator invocations in `src/ekap_aiq/benchmark/verify.py` (FR-094, SC-021)
- [X] T103 Implement the SC-003 flag-rate band check, **failing the run when the rate falls at or below the non-independence floor** rather than passing it in `src/ekap_aiq/benchmark/measures.py`
- [X] T104 [P] Build the labelled benchmark set for 5 countries × 26 questions in `data/benchmark/module_2_1.json` from published survey results, recording label source and date per pair

---

## Phase 9: Export and EKAP handoff

- [X] T105 Implement the per-cycle NDJSON export in `src/ekap_aiq/export/writer.py` per [contracts/export-schema.md](./contracts/export-schema.md) (FR-101, FR-102)
- [X] T106 Emit the accompanying exclusion report with a reason per excluded question in `src/ekap_aiq/export/writer.py` (FR-104)
- [X] T107 Enforce export invariants — delivered answers only, zero benchmark answers, zero mutations to any record or evidence artifact in `src/ekap_aiq/export/invariants.py` (FR-103, FR-105, SC-023)
- [X] T108 Record each export with time, producing actor, and included record set in `src/ekap_aiq/export/writer.py` (FR-106)
- [X] T109 [P] Implement the `EKAP_AOSQInteractions` projection in `src/ekap_aiq/export/ekap_projection.py` per [contracts/ekap-integration.md](./contracts/ekap-integration.md)

---

## Phase 10: Polish and cross-cutting concerns

- [X] T110 Implement `aiq telemetry summary | timings | fetches | cost` in `src/ekap_aiq/telemetry/reports.py` (FR-112)
- [X] T111 [P] Implement `aiq verify telemetry-hygiene` and `aiq verify no-credentials` asserting zero credentials and zero ground truth in any record in `src/ekap_aiq/telemetry/verify.py` (FR-110, FR-117)
- [X] T112 [P] Bring the review surface to WCAG 2.1 AA and wire an `npm run a11y` audit in `src/ekap_aiq/review/web/` and `package.json` (FR-119, SC-026)
- [X] T113 [P] Present evidence text in the portal's original language with any translation shown alongside, never in place of it in `src/ekap_aiq/review/web/evidence.py` (FR-120, FR-026)
- [X] T114 [P] Mark out-of-set-language best-effort answers wherever presented in `src/ekap_aiq/review/web/` and `src/ekap_aiq/export/writer.py` (FR-051)
- [X] T115 [P] Mark KB- and MSQ-sourced links with their provenance in the review surface and export in `src/ekap_aiq/review/api.py` and `src/ekap_aiq/export/writer.py` (FR-123)
- [X] T116 Run the full [quickstart.md](./quickstart.md) scenario set end to end and record results
- [X] T117 [P] Document the confirmed Vertex model ID, replacing the `gemini-flash` placeholder in `.env.example` and [contracts/configuration.md](./contracts/configuration.md)
- [X] T118 [P] Confirm the two open evidence-locus tags — #339 and #337 — and update `data/questions/module_2_1.json`

---

## Dependencies

```
Phase 1 Setup
   └─► Phase 2 Foundational ──┬─► Phase 3  US1 (P1)  ← MVP, no pipeline needed
                              ├─► Phase 4  US2 (P2)  ← needs Phase 2 portal + provider
                              │       └─► Phase 5  US3 (P3)  ← needs validated positions
                              │              └─► Phase 6  US4 (P4)  ← real runs
                              │                     ├─► Phase 7  US5 (P5)
                              │                     ├─► Phase 8  Benchmark
                              │                     └─► Phase 9  Export
                              └─────────────────────────► Phase 10 Polish
```

**Story independence**: US1 is fully independent — it runs on seeded data. US3 depends on US2 producing validated positions. US4 is independent of US2/US3 in code but required before any live run. US5 depends on US2 and US3 existing.

## Parallel execution examples

**Phase 2** — after T012, these run concurrently: `T013, T014, T016, T017, T018, T019, T020` (domain, no I/O), then `T029, T030, T034, T035`.

**Phase 3 (US1)** — `T036`, `T042`, `T043` touch different files and parallelize.

**Phase 4 (US2)** — `T047, T048, T050, T053, T054, T055` parallelize; the validator chain `T060 → T067` is sequential.

**Phase 6 (US4)** — the three link sources `T079, T080, T081` are fully parallel, as are `T086, T088, T089`.

**Phase 10** — `T111` through `T115`, plus `T117` and `T118`, all parallelize.

## Implementation strategy

**MVP = Phase 1 + Phase 2 + Phase 3.** That yields a working review surface over seeded data, which is the one story demonstrable with no pipeline running and the fastest way to put something in front of a stakeholder.

**First real run = through Phase 6.** Setup → Foundational → US2 → US3 → US4 gives an end-to-end pre-filled survey for the 5 PoC countries across all 26 questions.

**First defensible number = Phase 8.** Accuracy against the labelled set is what turns a demo into evidence. Note that **T104 (building the labelled set) is a human judgment task, not a coding task** — it is the long pole and should start in parallel with Phase 2 rather than waiting for Phase 8.

Deferrable for the PoC without weakening the result: Phase 7 (custom questions), Phase 9 (export), and T112–T113 (accessibility). US5 and export matter for EKAP adoption, not for proving the method.

## Task summary

| Phase | Tasks | Count |
|---|---|---|
| 1 — Setup | T001–T008 | 8 |
| 2 — Foundational | T009–T035 | 27 |
| 3 — US1 (P1) | T036–T046 | 11 |
| 4 — US2 (P2) | T047–T068 | 22 |
| 5 — US3 (P3) | T069–T077 | 9 |
| 6 — US4 (P4) | T078–T092 | 15 |
| 7 — US5 (P5) | T093–T096 | 4 |
| 8 — Benchmark | T097–T104 | 8 |
| 9 — Export | T105–T109 | 5 |
| 10 — Polish | T110–T118 | 9 |
| **Total** | | **118** |
