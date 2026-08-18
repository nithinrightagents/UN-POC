# Contract: JSON REST Surface

**Base path**: `/api/v1` — an `APIRouter` included in `portal/webapp.py`'s existing app ([research.md](../research.md) R1)
**Auth**: every operation requires `X-API-Key` — see [auth-and-limits.md](./auth-and-limits.md)
**Media type**: `application/json` on request and response bodies, always. No endpoint renders HTML, and no endpoint answers with a redirect (FR-API-001).

## Conventions

### Error envelope

Every non-2xx response is exactly:

```json
{ "error": { "code": "conflict", "message": "Cycle 'osi-2026' already exists.", "details": { "cycle_id": "osi-2026" } } }
```

| `code` | HTTP | Used for |
|---|---|---|
| `unauthorized` | 401 | Missing or wrong `X-API-Key` (FR-API-036) |
| `not_configured` | 503 | No secret configured on the service (FR-API-039) |
| `not_found` | 404 | Unknown cycle, unit, question, or job |
| `conflict` | 409 | Duplicate create (FR-API-006/009/010) |
| `invalid_request` | 422 | Missing/invalid field, including a human-answer read with no `role` (FR-API-029) |
| `precondition_failed` | 409 | Trigger with no portal URL or no indicators (FR-API-015) |
| `capacity_reached` | 429 | Concurrent-run cap hit (FR-API-014a); carries `Retry-After` |

No error body ever includes cycle, unit, question, answer, or score data beyond the identifiers the caller itself supplied (FR-API-036).

### Question identifiers

Every question-scoped path segment and response field uses the stored cycle-scoped `question_id` (`osi-2026:2.1.1`); the bare `indicator_id` (`2.1.1`) travels alongside for display only. Identifiers returned by the interface are accepted back unchanged (FR-API-011a).

---

## 1. Cycles (projects)

### `POST /api/v1/cycles` → 201

```json
{ "cycle_id": "osi-2026", "name": "UN E-Government Survey 2026",
  "questionnaire_ref": "UN MSQ 2026 Indicator Set", "project_type": "national_osi" }
```

Response: the created cycle (`cycle_id`, `name`, `questionnaire_ref`, `project_type`, `country_set`, `created_at`).
Also ensures the cycle's assessment session exists, as the portal's create does.
**409 `conflict`** when `cycle_id` exists — never an update (FR-API-006, R9).

### `GET /api/v1/cycles` → 200
`{ "cycles": [ …cycle… ] }`

### `GET /api/v1/cycles/{cycle_id}` → 200 / 404
One cycle, plus `question_count` and `unit_count`.

### `GET /api/v1/cycles/{cycle_id}/questions` → 200 / 404

```json
{ "questions": [ { "question_id": "osi-2026:2.1.1", "indicator_id": "2.1.1",
  "title": "…", "what": "…", "why": "…", "how": { … }, "module": "Institutional Framework",
  "evidence_locus": "national_portal_only", "benchmark_case": null, "answer_type": "binary" } ] }
```

---

## 2. Questions (indicators)

### `POST /api/v1/cycles/{cycle_id}/questions` → 201

```json
{ "indicator_id": "2.1.1", "title": "…", "what": "…", "why": "…", "how": "…",
  "module": "Institutional Framework", "evidence_locus": "national_portal_only",
  "benchmark_case": null }
```

Field-for-field the portal's form (`portal/admin.py:130-141`), including how `text` is composed as `"{title} — {what}"` and `how` is expanded into the four-key guidance dict — the API must produce a `Question` indistinguishable from a portal-created one (FR-API-009).

Response: the stored question, including its assigned `question_id`.
**409 `conflict`** when that `indicator_id` already exists in this cycle; the same code under a different cycle is accepted (FR-API-009).

> **Portal parity note**: the portal also rewrites `cycle.questionnaire_ref` to `"<name> Custom Questionnaire Set (N indicators)"` on every add (`admin.py:170-177`). The API performs the same rewrite, so a cycle built through either surface reads identically.

---

## 3. Units

### `POST /api/v1/cycles/{cycle_id}/units` → 201

```json
{ "country_id": "DNK", "display_name": "Denmark", "url": "https://www.borger.dk", "unit_type": "country" }
```

`unit_type` ∈ `country` | `city`. Response includes the generated `portal_id` (FR-API-011).
**409 `conflict`** when `(cycle_id, country_id)` already exists — regardless of URL, since the store holds at most one unit per cycle and country/city (FR-API-010, R9). This replaces today's silent no-op.

### `GET /api/v1/cycles/{cycle_id}/units` → 200
`{ "units": [ { "portal_id", "country_id", "display_name", "unit_type", "resolved_url", "has_msq", "latest_job_state", "published" } ] }`

---

## 4. AI assessment

### `POST /api/v1/cycles/{cycle_id}/units/{portal_id}/assessment` → 202

Body optional: `{ "actor_id": "integration-client" }`.

```json
{ "job_id": "job-…", "state": "running", "cycle_id": "osi-2026", "portal_id": "portal-…",
  "questions_total": 111, "questions_completed": 0, "already_running": false,
  "created_at": "2026-08-18T10:00:00Z" }
```

- Returns before the run finishes; the run proceeds in the background (FR-API-013, SC-003).
- **Idempotent**: a unit already running returns 202 with that job and `already_running: true` (FR-API-014).
- **409 `precondition_failed`**: unit has no `resolved_url`, or the cycle has no indicators (FR-API-015).
- **429 `capacity_reached`**: cap reached (FR-API-014a). Not returned for the idempotent case.
- **404 `not_found`**: unknown cycle or unit.

### `GET /api/v1/cycles/{cycle_id}/units/{portal_id}/assessment` → 200

```json
{ "state": "running", "job_id": "job-…", "questions_total": 111, "questions_completed": 42,
  "failure_cause": null, "triggered_by": "api",
  "created_at": "…", "updated_at": "…", "outcomes": null }
```

- `state` ∈ `running` | `done` | `failed` — never anything else (FR-API-018).
- Never triggered → `{ "state": "never_triggered", "job_id": null, "questions_total": <cycle total>, "questions_completed": 0 }` at **200**, not 404: the unit exists, the run does not (FR-API-019).
- `failed` carries `failure_cause` and the progress reached (FR-API-020); `service_stopped_mid_run` identifies a restart.
- Reports the **latest** job for the unit; `outcomes` (delivered/escalated/unassessable counts) is populated once terminal.

### `GET /api/v1/cycles/{cycle_id}/units/{portal_id}/results` → 200

```json
{ "complete": false, "questions_total": 111, "questions_completed": 42,
  "results": [ { "question_id": "osi-2026:2.1.1", "indicator_id": "2.1.1",
    "assessed": true, "answer": true, "confidence": 88,
    "justification": "…", "evidence_url": "https://…", "evidence_missing": false,
    "blocked": false, "blank_reason": null } ] }
```

- `complete` is true only when the latest job is `done` (FR-API-024).
- A blocked question: `answer: null`, `blocked: true`, `blank_reason` carrying spec 004's reason tag (FR-API-023).
- A question the run has not reached: `assessed: false` with null answer — distinct from a blocked one.

---

## 5. Human assessor answers

### `POST /api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers` → 201

```json
{ "question_id": "osi-2026:2.1.1", "role": "A", "actor_id": "assessor-1",
  "answer": true, "evidence_url": "https://…", "notes": "…" }
```

- `evidence_url` and `notes` optional; `question_id`, `role`, `actor_id`, `answer` required (422 otherwise) (FR-API-026).
- Recorded exactly as the assessor portal records it — same dataclass, same AI-suggestion linkage, and it triggers the same A/B discrepancy recomputation (FR-API-027).
- Response echoes the stored submission (`submission_id`, `role`, `answer`, `submitted_at`).

### `GET /api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers?role=A` → 200

```json
{ "role": "A", "answers": [ { "question_id": "osi-2026:2.1.1", "indicator_id": "2.1.1",
  "answered": true, "answer": true, "evidence_url": null, "notes": null,
  "actor_id": "assessor-1", "submitted_at": "…" } ] }
```

- **`role` is required.** Omitted → **422 `invalid_request`**, never a both-roles default (FR-API-029).
- Only the named role's submissions appear anywhere in the response (FR-API-028, SC-006).
- Every question in the cycle is listed, `answered` separating answered from not (FR-API-030); a revised answer returns the current one.

---

## 6. Publication

### `POST /api/v1/cycles/{cycle_id}/units/{portal_id}/publication` → 201

Body: `{ "actor_id": "senior-reviewer" }`

```json
{ "publication_id": "pub-…", "score": 0.72, "published_by": "senior-reviewer",
  "published_at": "…", "breakdown": [ { "question_id": "…", "indicator_id": "…", "final_answer": true } ] }
```

Final answers come from the extracted, shared precedence — arbitration → A/B agreement → lone human → adjudicated AI — with no invented answers (FR-API-032, SC-007).

### `GET /api/v1/cycles/{cycle_id}/units/{portal_id}/publication` → 200

Latest publication (FR-API-033). Never published → `{ "published": false, "score": null, "breakdown": [] }` at 200 — explicitly not a zero score (FR-API-034).

---

## Out of contract

No endpoint for: MSQ upload, escalation queue or dispositions, benchmarks, answer export, public rankings, run cancellation, entity updates or deletes, or any operation returning both assessor roles. All are listed under the spec's Out of Scope.
