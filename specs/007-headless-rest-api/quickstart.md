# Quickstart & Validation: Headless Assessment REST API

**Feature Directory**: `specs/007-headless-rest-api`
**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Contracts**: [contracts/](./contracts/)

Eight scenarios, each mapping to a user story or success criterion in the spec. Scenarios 1–6 need no model credentials and no network; only Scenario 7 spends real model budget.

---

## Prerequisites

```bash
pip install -e ".[dev]"
playwright install chromium          # only needed for Scenario 7 (a real run)
```

`.env` additions for this feature (see [contracts/auth-and-limits.md](./contracts/auth-and-limits.md)):

```
AIQ_API_KEY=local-dev-secret
AIQ_MAX_CONCURRENT_ASSESSMENT_RUNS=2
```

Verify the parameters are wired and the secret is masked:

```bash
aiq config show | grep -E "api_key|max_concurrent"
```

**Expected**: `api_key` shows `***` (not the literal secret) with source `configured`, and `max_concurrent_assessment_runs` shows `2`. A visible secret here is a failure of R6 — the same `as_dict()` is written into `configuration_snapshots`.

## Setup

```bash
aiq db init
aiq seed demo          # optional: two projects, seeded units, an A/B discrepancy case
aiq serve              # http://127.0.0.1:8080 — portal and /api/v1 in one process
```

Startup log should report the interrupted-job sweep (`swept N interrupted assessment job(s)`), `N=0` on a clean start.

Throughout, `-H "X-API-Key: local-dev-secret"` is abbreviated as `$AUTH`.
In PowerShell use `curl.exe` (not the `Invoke-WebRequest` alias) so the `-H`/`-d` flags behave as written.

---

## Scenario 1 — Full lifecycle without a browser (US1, SC-001, SC-002)

```bash
# 1. create a cycle
curl -s -X POST localhost:8080/api/v1/cycles $AUTH -H 'content-type: application/json' \
  -d '{"cycle_id":"api-demo","name":"API Demo Cycle","questionnaire_ref":"Custom","project_type":"national_osi"}'

# 2. add an indicator (note the returned question_id: "api-demo:2.1.1")
curl -s -X POST localhost:8080/api/v1/cycles/api-demo/questions $AUTH -H 'content-type: application/json' \
  -d '{"indicator_id":"2.1.1","title":"National portal exists","what":"A single national portal is reachable","why":"Baseline OSI indicator","how":"Open the portal root and confirm it resolves","module":"Institutional Framework","evidence_locus":"national_portal_only"}'

# 3. register a unit (note the returned portal_id)
curl -s -X POST localhost:8080/api/v1/cycles/api-demo/units $AUTH -H 'content-type: application/json' \
  -d '{"country_id":"DNK","display_name":"Denmark","url":"https://www.borger.dk","unit_type":"country"}'

# 4. read it all back
curl -s localhost:8080/api/v1/cycles/api-demo $AUTH
curl -s localhost:8080/api/v1/cycles/api-demo/questions $AUTH
curl -s localhost:8080/api/v1/cycles/api-demo/units $AUTH
```

**Expected**: every call returns JSON with no redirect and no HTML; each create returns the identifier the next step needs; `question_id` is `api-demo:2.1.1` with `indicator_id` `2.1.1` alongside.

**Then open `http://127.0.0.1:8080/admin`** — the cycle, its indicator, and its unit are all present (FR-API-003, US1 scenario 7). Conversely, a project created in the portal appears in `GET /api/v1/cycles`.

---

## Scenario 2 — Duplicate creates are refused, not silently absorbed (FR-API-006/009/010, R9)

Re-run each create from Scenario 1 verbatim.

**Expected**: all three return **409** `conflict` naming the existing entity, and nothing is modified — re-read the cycle and confirm `name` and `questionnaire_ref` are unchanged.

Then register a *different* URL for the same country:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8080/api/v1/cycles/api-demo/units $AUTH \
  -H 'content-type: application/json' \
  -d '{"country_id":"DNK","display_name":"Denmark","url":"https://different.example","unit_type":"country"}'
```

**Expected**: **409**, not 201. This is the amended FR-API-010 — the store holds at most one unit per cycle and country. Confirm `GET .../units` still shows exactly one Denmark unit with its original URL. (Before this feature, the portal's equivalent form silently discarded this and redirected as if it had succeeded.)

---

## Scenario 3 — Access control matrix (US5, SC-008)

```bash
for path in cycles cycles/api-demo cycles/api-demo/questions cycles/api-demo/units; do
  curl -s -o /dev/null -w "$path no-key:%{http_code} " localhost:8080/api/v1/$path
  curl -s -o /dev/null -w "wrong-key:%{http_code}\n" -H 'X-API-Key: wrong' localhost:8080/api/v1/$path
done
```

**Expected**: every path returns **401** for both, with an error body containing no cycle/unit/question data. Trigger with a wrong key and confirm **no** job row appears (`GET .../assessment` still reports `never_triggered`) — a refused call has no side effects.

Then unset `AIQ_API_KEY`, restart, and repeat: the service **starts normally**, `/admin` and `/` work, and `/api/v1/**` returns **503** `not_configured` (FR-API-039).

---

## Scenario 4 — Human answers stay blind (US3, SC-006)

```bash
Q=api-demo:2.1.1; U=<portal_id>
curl -s -X POST localhost:8080/api/v1/cycles/api-demo/units/$U/human-answers $AUTH -H 'content-type: application/json' \
  -d "{\"question_id\":\"$Q\",\"role\":\"A\",\"actor_id\":\"assessor-1\",\"answer\":true,\"evidence_url\":\"https://www.borger.dk\",\"notes\":\"found\"}"
curl -s -X POST localhost:8080/api/v1/cycles/api-demo/units/$U/human-answers $AUTH -H 'content-type: application/json' \
  -d "{\"question_id\":\"$Q\",\"role\":\"B\",\"actor_id\":\"assessor-2\",\"answer\":false}"

curl -s "localhost:8080/api/v1/cycles/api-demo/units/$U/human-answers?role=A" $AUTH
curl -s "localhost:8080/api/v1/cycles/api-demo/units/$U/human-answers?role=B" $AUTH
curl -s -o /dev/null -w '%{http_code}\n' "localhost:8080/api/v1/cycles/api-demo/units/$U/human-answers" $AUTH
```

**Expected**: role A's read returns only `answer: true` / `assessor-1`; role B's only `answer: false` / `assessor-2`; **neither response mentions the other role anywhere**. The role-less read returns **422**, not both roles. The second submission (no `evidence_url`, no `notes`) was accepted.

Cross-check in the portal: `/assessor/api-demo/<portal_id>?role=A` shows A's answer only — the API and portal enforce the same scoping.

---

## Scenario 5 — Job status survives a restart (US2, FR-API-017/018/019)

1. `GET .../assessment` **before** any trigger → `state: "never_triggered"`, `job_id: null`.
2. Trigger, then **stop the server** (Ctrl-C) while `state` is `running`.
3. Restart `aiq serve`. The startup log reports `swept 1 interrupted assessment job(s)`.
4. `GET .../assessment`.

**Expected**: `state: "failed"`, `failure_cause: "service_stopped_mid_run"`, `questions_completed` equal to whatever finished before the stop — never `running`, never a 404, and distinguishable from both `done` and `never_triggered`.
5. Re-trigger: a **new** `job_id` starts and only the unfinished questions are dispatched (`process_unit` returns "already terminal" for the rest); the previous failed job remains readable in the table (FR-API-021).

---

## Scenario 6 — Trigger semantics: idempotency, preconditions, capacity (FR-API-014/014a/015)

| Case | Command | Expected |
|---|---|---|
| Unit with no URL | trigger a unit registered without a URL | **409** `precondition_failed` (`unit_has_no_url`), no job row |
| Cycle with no indicators | create an empty cycle + unit, trigger | **409** `precondition_failed` (`cycle_has_no_questions`) |
| Double trigger | trigger the same unit twice quickly | both **202**, **same `job_id`**, second has `already_running: true` |
| Simultaneous trigger | two triggers in parallel (`&`) | exactly one job row exists for the unit |
| Capacity | set `AIQ_MAX_CONCURRENT_ASSESSMENT_RUNS=1`, restart, trigger two *different* units | first 202, second **429** `capacity_reached` with `Retry-After`; re-triggering the *running* unit still returns 202 (SC-011) |

Also confirm the trigger returns in under two seconds even against a 111-indicator cycle (SC-003) — time it with `curl -w '%{time_total}'`.

---

## Scenario 7 — A real run, end to end (US1, FR-API-022/023/024, SC-010)

Requires Vertex AI credentials (`GOOGLE_CLOUD_PROJECT`, `GOOGLE_GENAI_USE_VERTEXAI=1`) and Chromium. **This spends real model budget.**

```bash
curl -s -X POST localhost:8080/api/v1/cycles/api-demo/units/$U/assessment $AUTH
while :; do curl -s localhost:8080/api/v1/cycles/api-demo/units/$U/assessment $AUTH; sleep 10; done
curl -s localhost:8080/api/v1/cycles/api-demo/units/$U/results $AUTH
```

**Expected**:
- `questions_completed` climbs monotonically and never exceeds `questions_total` (SC-005).
- Polling `results` mid-run returns `complete: false` with the finished questions only (FR-API-024).
- Once `state: "done"`, each result carries `answer`, `confidence`, `justification`, and `evidence_url`; any blocked question has `answer: null`, `blocked: true`, and spec 004's `blank_reason` (FR-API-023).
- **Telemetry parity** (SC-010): `aiq telemetry cost --session api-demo-workflow-session` and `aiq telemetry fetches --session …` show entries for this run, identical in kind to a portal- or CLI-triggered run.

---

## Scenario 8 — Publication parity with the portal (US4, SC-007)

Submit A/B answers for three questions — one where A and B agree, one where they differ, one left to the AI — then:

```bash
curl -s -X POST localhost:8080/api/v1/cycles/api-demo/units/$U/publication $AUTH \
  -H 'content-type: application/json' -d '{"actor_id":"senior-reviewer"}'
curl -s localhost:8080/api/v1/cycles/api-demo/units/$U/publication $AUTH
```

**Expected**: `score` and `breakdown` are byte-for-byte the values the portal's own publish button produces for the same unit — guaranteed by both calling one extracted `_final_answer` (R10). Confirm the record is visible at `/public/api-demo/<portal_id>`.

Also: `GET .../publication` for a never-published unit returns **200** with `published: false` and `score: null` — not a zero score (FR-API-034).

---

## Automated suite

```bash
pytest tests/unit/test_api_contract.py -v         # error envelope, status codes, identifiers
pytest tests/unit/test_api_auth.py -v             # Scenario 3 matrix incl. no-side-effect
pytest tests/unit/test_api_jobs.py -v             # Scenarios 5-6: lifecycle, sweep, cap, idempotency
pytest tests/unit/test_api_human_blindness.py -v  # Scenario 4 across every unit x question x role
pytest tests/unit/test_api_publication.py -v      # Scenario 8 parity against the portal helper
pytest tests/unit/test_modular_structure.py -v    # existing architecture invariants still hold
pytest -q                                          # full suite: no portal regression (SC-009)
```

Tests use FastAPI's `TestClient` against a temp-file SQLite database with `run_assessment_job` patched to a fake — no model credentials, no network, no Chromium. Scenarios 5–6 exercise the sweep and cap by calling `sweep_interrupted_jobs()` and `start_assessment_job()` directly rather than by restarting a server.
