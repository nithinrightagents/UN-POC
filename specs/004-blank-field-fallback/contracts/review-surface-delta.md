# Contract: Review surface delta

Extends spec 001's FR-043 family (per-question review presentation). States only what changes in `review/query.py`, `review/unlock.py`, and `review/web/*`.

## `build_question_review()` — behavior for a blocked unit

| Aspect | Today | This feature |
|---|---|---|
| `escalated` (blocked) detection | `unit_state == "escalated"` only | `unit_state in {"escalated", "unassessable"}` (research R2) |
| Reason shown | Raw `escalation_reason` enum string | `ReasonTag.text` from [reason-tags.md](./reason-tags.md), via new `reason_tag` field |
| `delivered_answer` when no decision yet | `None` (renders as literal text `"None"` in the template today) | Still `None` at the data layer; template renders it as an explicit blank/placeholder, never the word "None" |
| `agent_positions` | Latest adjudicated round only | Every round, when blocked (so a disagreement block shows its full history, FR-BF-009) |
| Attempt history | Not exposed | New `attempt_history: AttemptHistoryView` field, always present when blocked |

## `portal_review_status()` — behavior change

`escalated_question_ids` now includes `UNASSESSABLE` units, not only `ESCALATED` ones (research R2). `unlocked`/`terminal_count` semantics are unchanged — `UNASSESSABLE` already counted toward unlocking; only the per-question labeling was incomplete.

## Web templates

- `questions.html`: the `escalated` badge is shown for every question in the (now-correct) `escalated_question_ids` list, regardless of whether the unit's actual state is `ESCALATED` or `UNASSESSABLE`.
- `question.html`:
  - The "Escalated: `{raw enum}`" line is replaced with the `reason_tag` text.
  - "Proposed answer" is not rendered as the literal string `None`; a blocked question with no proposed answer shows an explicit blank/placeholder state instead.
  - The Approve form is **not rendered** when `view.system_proposed_answer is None` (there is nothing to approve; submitting would deliver `None`, violating FR-BF-002). Edit and Reject-and-override remain available — Edit is the primary path for a reviewer supplying the first answer to a blank field (research R7).
  - A new attempt-history disclosure (`render_attempt_history_html`, alongside the existing `render_agent_detail_html` in `detail.py`) is rendered whenever `view.escalated` is true, presenting `attempt_history`'s resolution attempts, reachability/verification attempt counts, retry counts, and points of disagreement — all from data already captured (FR-BF-008, FR-BF-009).
  - `evidence.py`'s existing "evidence missing" branch already satisfies FR-BF-010 for a blocked unit with no evidence; no change needed there.

## Explicitly unchanged

- The URL structure and route handlers in `review/web/app.py` (`/portal/{id}/question/{id}`, `/approve`, `/edit`, `/reject`) — same endpoints, same forms, conditionally rendered rather than restructured.
- `review/escalations.py` and its `/escalation-queue`-style views — the coordinator-facing escalation-queue disposition flow is untouched; this feature's resolution path is the per-question screen, not the queue (see data-model.md "Explicitly unchanged").
- WCAG 2.1 AA conformance (FR-119) — the new attempt-history disclosure follows the existing `<details>/<summary>` pattern already used for per-agent breakdown, which is already accessible without JavaScript.
