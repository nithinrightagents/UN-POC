# Contract: Assessor Agent

**Satisfies**: FR-008–FR-013, FR-108, FR-010 (independence) | **Data model**: [../data-model.md](../data-model.md) §Assessor Agent Run

One invocation evaluates **one question** against **one target portal** in **one round**. N invocations per unit, `N ≥ 2`, each in its own ADK session.

## Input schema — closed

```jsonc
{
  "session_id": "string",
  "agent_index": 0,                    // selects the configuration variant (research R7)
  "round_number": 1,
  "question": {
    "question_id": "string",
    "text": "string",
    "answer_type": "binary | scalar | enum",
    "answer_options": ["..."]          // present when answer_type = enum
  },
  "portal": {
    "portal_id": "string",
    "resolved_url": "https://...",
    "detected_language": "en",
    "language_in_supported_set": true
  },
  "addendum": {                         // optional; retry only
    "kind": "validation_gaps | disagreement_points",
    "items": ["string"]
  }
}
```

**This schema is closed, and that is the point.** There is no field capable of carrying another Assessor Agent's answer, confidence, justification, or evidence. FR-010 is therefore a schema property rather than a review discipline — a leak fails validation at the boundary instead of surviving into a run.

Two rules govern `addendum`:

- `validation_gaps` — the specific gaps from this agent's own Validation Result (FR-080). Never another agent's.
- `disagreement_points` — the points of disagreement for the unit (FR-030). **Must not attribute any position to an identified agent** (FR-031). "The two positions differ on whether a mobile app is offered" is admissible; "Agent 1 answered yes" is not.

## Output schema

```jsonc
{
  "run_id": "string",
  "answer": <conforms to question.answer_type>,
  "confidence": 87,                     // 0–100 integer
  "justification": "plain-language string",
  "evidence": {
    "resolved_url": "https://...",
    "capture_ref": "blob reference",
    "element_reference": { "css_path": "...", "text_hash": "...", "sibling_index": 0 },
    "element_text": "string",
    "element_text_original_language": "string",   // required when out-of-set language
    "element_text_translation": "string | null"
  },
  "auth_boundary_observed": false,
  "auth_boundary_url": null,
  "model_identity": "provider/model@version"
}
```

## Invariants

| # | Invariant | Requirement |
|---|---|---|
| A1 | `confidence` derives solely from evidence quality and source authority **this agent** observed | FR-013 |
| A2 | `confidence` is recorded before any cross-agent comparison occurs | FR-013 |
| A3 | `answer` conforms to `question.answer_type` | FR-012 |
| A4 | All three evidence components present, or the run reports failure — never a partial evidence set | FR-021 |
| A5 | When `auth_boundary_observed` is true, `answer` **must be null**. No answer inferred from public pages. | FR-108 |
| A6 | Out-of-set-language runs retain original-language element text alongside any translation | FR-026 |

**A5 is the one that needs a test rather than a code review.** An agent that reaches a sign-in wall has strong, well-evidenced grounds to answer "feature absent" — the public page genuinely does not show the feature, the screenshot is real, and the evidence verifies cleanly against the live page. Neither the Validator nor the Adjudicator catches it, and two agents can reach it independently and agree. The only defence is refusing to answer at the point of detection.

## Preconditions

- `N ≥ 2` or the run is rejected outright (FR-009).
- `question.requires_authenticated_access` is false — such questions never reach an agent (FR-107).
- Portal language is in the supported set, **or** a human authorized a best-effort attempt (FR-018), in which case the confidence ceiling applies downstream.

## Error outcomes

| Outcome | Effect |
|---|---|
| Target unreachable after bounded attempts | Unit → `escalated` (unreachable portal), FR-071 |
| Authentication boundary detected | Unit → `escalated` (requires authenticated access), FR-109 |
| Evidence capture failed | Run reports failure; confidence capped below the acceptance threshold, FR-024 |
