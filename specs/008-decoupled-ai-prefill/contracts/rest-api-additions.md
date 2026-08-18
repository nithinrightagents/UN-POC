# Contract: REST API Additions and Changes

**Feature Directory**: `specs/008-decoupled-ai-prefill`
**Spec**: [spec.md](../spec.md) · **Extends**: `specs/007-headless-rest-api/contracts/rest-api.md`

Two new endpoints, three changed ones. Every addition follows spec 007's existing conventions — same `/api/v1` prefix, same `X-API-Key` router dependency, same error envelope, same cycle-scoped `question_id` — so FR-PF-048's "no separate authentication mechanism" is satisfied by inheritance rather than by re-implementation.

---

## 1. New — read a unit's prefills

```http
GET /api/v1/cycles/{cycle_id}/units/{portal_id}/prefills
X-API-Key: <secret>
```

**200**

```json
{
  "run_id": "job_a1b2c3",
  "generated_at": "2026-08-18T09:12:44Z",
  "complete": true,
  "prefills": [
    {
      "question_id": "c-2024:2.1.1",
      "indicator_id": "2.1.1",
      "suggested": true,
      "answer": true,
      "confidence": 82,
      "justification": "The portal's services index lists an online tax filing form ...",
      "evidence_url": "https://example.gov/services/tax",
      "supplying_source": "prior_survey_kb",
      "agreement_outcome": "uncontested",
      "confidence_gap": 3,
      "unselected_position": null,
      "resolver_reasoning": null,
      "reason": null,
      "reason_text": null
    },
    {
      "question_id": "c-2024:2.1.2",
      "indicator_id": "2.1.2",
      "suggested": true,
      "answer": false,
      "confidence": 54,
      "justification": "No e-participation calendar is published ...",
      "evidence_url": "https://example.gov/participate",
      "supplying_source": "search",
      "agreement_outcome": "disputed",
      "confidence_gap": 24,
      "unselected_position": {
        "answer": true,
        "confidence": 71,
        "justification": "A consultations page exists but ...",
        "evidence_url": "https://example.gov/consultations"
      },
      "resolver_reasoning": "Position 1 cites a page that lists past consultations only ...",
      "reason": null,
      "reason_text": null
    },
    {
      "question_id": "c-2024:2.1.3",
      "indicator_id": "2.1.3",
      "suggested": false,
      "answer": null,
      "confidence": null,
      "justification": null,
      "evidence_url": null,
      "supplying_source": null,
      "agreement_outcome": null,
      "confidence_gap": null,
      "unselected_position": null,
      "resolver_reasoning": null,
      "reason": "budget_reached",
      "reason_text": "No suggestion: the run's budget was reached before this indicator"
    }
  ]
}
```

**Contract points**

| Point | Requirement |
|---|---|
| One entry per question currently in the cycle, always | FR-PF-033, FR-PF-043 |
| `suggested: true` ⟹ `answer` non-null and `reason` null; `false` ⟹ the reverse | FR-PF-043, SC-008 |
| Exactly one `answer`, never a list | FR-PF-028a, SC-006a |
| `unselected_position` present ⟺ `agreement_outcome = "disputed"` | FR-PF-026c, FR-PF-013 |
| `question_id` is the same stored cycle-scoped identifier every other endpoint uses | FR-PF-043 |
| **No `role` parameter and no role field** | FR-PF-046 |
| No human submission appears in the response | FR-PF-046 |
| `complete: false` when a run is in flight; unreached questions carry `suggested: false, reason: null` | in-flight edge case |
| A unit with no run ever: `200`, `run_id: null`, every entry `suggested: false, reason: null` | FR-PF-007 |

**Why there is no `role` query parameter.** Spec 007's human-answer endpoints require one and refuse without it, because blindness there is a query-shape guarantee. A prefill is shown identically to both roles (FR-PF-012), so accepting a `role` here would imply a role-scoping that does not exist and invite a caller to assume the response differs. The blindness guarantee is instead preserved by the response carrying no submissions at all.

**404** — unknown cycle or unit, standard envelope.

---

## 2. New — declare an assessor's completion

```http
POST /api/v1/cycles/{cycle_id}/units/{portal_id}/completions
X-API-Key: <secret>
Content-Type: application/json

{ "role": "A", "actor_id": "assessor-nl-1" }
```

**201**

```json
{
  "completion_id": "comp_x9y8",
  "role": "A",
  "actor_id": "assessor-nl-1",
  "declared_at": "2026-08-18T09:40:02Z",
  "indicator_count": 111
}
```

**409 — incomplete** (FR-PF-044, SC-004b)

```json
{
  "error": {
    "code": "incomplete_assessment",
    "message": "Assessor A has 3 indicators outstanding.",
    "details": {
      "role": "A",
      "answered_count": 108,
      "total_indicators": 111,
      "outstanding_question_ids": ["c-2024:2.3.4", "c-2024:2.5.1", "c-2024:2.6.7"]
    }
  }
}
```

**400** — `role` not `A` or `B`, reusing spec 007's `InvalidRequest`.
**404** — unknown cycle or unit.

Re-declaring an already-complete unit returns `201` with a new `completion_id`. It is not an error — the operation is idempotent in effect, append-only in record.

### Read the declaration state

```http
GET /api/v1/cycles/{cycle_id}/units/{portal_id}/completions
```

**200**

```json
{
  "ready_to_publish": false,
  "roles": {
    "A": { "declared": true,  "actor_id": "assessor-nl-1", "declared_at": "...",
           "answered_count": 111, "total_indicators": 111,
           "outstanding_question_ids": [], "complete": true },
    "B": { "declared": false, "actor_id": null, "declared_at": null,
           "answered_count": 96,  "total_indicators": 111,
           "outstanding_question_ids": ["c-2024:2.4.1", "..."], "complete": false }
  },
  "blocking_reason": "Assessor B has not declared their assessment complete."
}
```

This read is what FR-PF-005h serves programmatically, and it is deliberately not role-scoped — it reports *counts* per role, never answers, so it exposes progress without exposing positions.

---

## 3. Changed — publish

```http
POST /api/v1/cycles/{cycle_id}/units/{portal_id}/publication
```

Unchanged on success. **New refusal** (FR-PF-045):

**409**

```json
{
  "error": {
    "code": "assessment_incomplete",
    "message": "Assessor B has not declared their assessment complete.",
    "details": {
      "roles": {
        "A": { "declared": true,  "complete": true },
        "B": { "declared": false, "complete": false }
      }
    }
  }
}
```

The success response's `score` and `breakdown` now cover every indicator, because nothing incomplete can reach this point. Both surfaces call the same `publication_readiness` and the same `final_answer`, so SC-013's identical-output guarantee is structural.

---

## 4. Changed — assessment results

```http
GET /api/v1/cycles/{cycle_id}/units/{portal_id}/results
```

Per FR-PF-047, a question with no suggestion now reports the `PrefillReason` taxonomy instead of spec 004's blank-field `reason_tag`:

```json
{
  "question_id": "c-2024:2.1.3",
  "assessed": false,
  "answer": null,
  "reason": "unresolved_disagreement",
  "reason_text": "No suggestion: the two independent assessments could not be reconciled"
}
```

`reason` is the new machine-readable field; `reason_text` is the rendered label. Spec 007's FR-API-023, which derived its text from spec 004's `reason_tag`, is superseded for prefill-produced records. **Historical records keep their old reasons** — a unit terminated `escalated` by a pre-feature run still renders through `reason_tag()`, since the reader picks by which field the record carries ([research.md](../research.md) R11).

A `no_suggestion` terminal state must be counted as terminal in this endpoint's completeness derivation, alongside `delivered` and `unassessable` ([research.md](../research.md) R1).

---

## 5. Changed — human answer submission

```http
POST /api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers
```

Request and response shapes are unchanged. What changes is invisible to the caller: `ai_suggested_answer` and `ai_suggestion_accepted` are now derived from `latest_prefill()` rather than from the `agent_index == -1` scan at [human.py:71-76](../../../src/api/routers/human.py#L71-L76) ([research.md](../research.md) R10).

This matters despite being invisible. It is what makes SC-012's "did the assessor take the suggestion" measure count the suggestion the assessor actually saw.

---

## 6. Error codes

Two added to spec 007's seven. Both reuse the existing envelope and neither needs a new HTTP status:

| Code | Status | Raised by |
|---|---|---|
| `incomplete_assessment` | 409 | completion declaration, when indicators are outstanding |
| `assessment_incomplete` | 409 | publish, when a required role has not declared |

They are separate codes because the caller's next action differs: the first says "answer these indicators", the second says "have that role declare".

---

## 7. Parity checklist

FR-PF-042 requires every capability this feature adds or changes to be reachable programmatically. Enumerated so SC-014 has something to check against:

| Capability | Portal | API | Requirement |
|---|---|---|---|
| See a unit's prefills | assessor screen | `GET .../prefills` | FR-PF-042, FR-PF-043 |
| See the reason for no suggestion | assessor screen | same endpoint, `reason` | FR-PF-034 |
| See the unselected position on a contested question | assessor screen | same endpoint, `unselected_position` | FR-PF-013 |
| Submit an answer | assessor form | `POST .../human-answers` | pre-existing |
| See what remains before completing | progress indicator | `GET .../completions` | FR-PF-005h |
| Declare completion | complete button | `POST .../completions` | FR-PF-044 |
| Publish under the revised rules | admin publish | `POST .../publication` | FR-PF-045 |
| Trigger a prefill run | admin button | `POST .../assessments` (spec 007) | FR-PF-036 |
| See a run's per-reason summary | admin run status | `GET .../assessments/{job_id}` | FR-PF-041 |

Every row has both columns filled. That is the whole of SC-014.
