# Phase 0 Research: Automated Dynamic Discrepancy Detection and Reconciliation

**Feature Directory**: `specs/012-portal-discrepancy-reconciliation`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-08-24

Twelve decisions. Each was reached by reading the call sites rather than by inference, and each records what was rejected.

---

## R1 — A reconciliation round is a lifecycle record, not a derived count

**Decision**: Add a `reconciliation_rounds` table whose rows carry `round_id`, `session_id`, `portal_id`, the disputed set that opened them, `opened_by` (`automatic` | `senior_reviewer`), the opening reason, the opening actor, `state` (`open` | `resolved` | `exhausted` | `not_required`), and the closing timestamp. `state` is updated in place on close, following the `assessment_jobs` precedent ([repositories.py:866](../../src/shared/persistence/repositories.py#L866) `update_assessment_job_state`), not the append-only audit-table convention.

**Rationale**: FR-DR-030 caps automatic rounds at one, FR-DR-031 requires knowing how many were consumed and who opened each, and FR-DR-039 requires a manually re-opened round to behave identically to the automatic one. None of that is derivable from what exists today. The obvious reuse — counting `EscalationQueueItem`s with `reason=PORTAL_DISCREPANCY` — is **wrong**, and quietly so: the idempotency guard at [discrepancy.py:111-116](../../src/portal/discrepancy.py#L111-L116) suppresses a second item when the disagreement set is unchanged, so a unit that has been through two rounds over the same disputed indicators has exactly one queue item. A cap counted that way would never fire.

A round is a lifecycle object with an open state and a terminal state, exactly like `assessment_jobs`. The audit trail it needs is already carried elsewhere and stays append-only: `discrepancy_cases` records every comparison, `joint_answers` records every settlement. Nothing that must be reconstructable later is stored only in a mutable column.

**Alternatives considered**: A pure append-only design with an `opened` row and a `closed` row per round was rejected — every reader would have to fold the pair to answer "is a round open", which is the single most-asked question in this feature (routing, badge, and the sign-off gate all ask it). Deriving rounds from escalation items was rejected for the counting reason above.

---

## R2 — A joint answer must be visible to `_compare()`, or nothing downstream can ever close

**Decision**: `_compare()` gains a joint-answer overlay. For each commonly answered indicator, if a joint answer exists for the unit, both sides take the joint value before the comparison. Originals are never rewritten.

**Rationale**: This is the finding that most changes the shape of the work, and it contradicts the framing that the engine is already complete. [`_compare()`](../../src/portal/discrepancy.py#L23-L45) reads exactly two things per indicator — `latest_human_submission(..., AssessorRole.A)` and `latest_human_submission(..., AssessorRole.B)`. A joint answer stored in its own table is invisible to it. Follow the consequence through:

- assessors agree a joint answer on every disputed indicator;
- `_compare()` still sees A's original and B's original, still differing;
- the rate does not move;
- FR-DR-032 ("where the rate is at or below tolerance at the end of a round, close as resolved") can never be satisfied;
- the badge never leaves red;
- and FR-DR-033 puts the unit into persistent discrepancy despite the assessors having agreed on everything.

The feature would fail at its own success condition. The overlay is the smallest change that makes FR-DR-026, FR-DR-032, FR-DR-041, and SC-005 simultaneously true.

Because both public entry points route through `_compare()`, the read-only [`compute_portal_discrepancy`](../../src/portal/discrepancy.py#L48) and the writing [`recompute_portal_discrepancy`](../../src/portal/discrepancy.py#L72) inherit the overlay together and cannot disagree about what the rate is.

**Alternatives considered**:

- *Write the joint answer as a submission row for both roles.* Rejected. It makes the rate fall with no engine change and `final_answer` works untouched — genuinely tempting. But it forges the audit trail: the record would show Assessor A independently changing their mind at the moment B did, which is precisely the blind-independence claim the whole A/B design exists to support. It would also corrupt `ai_suggestion_accepted` ([assessor.py:163-165](../../src/portal/assessor.py#L163-L165)), silently biasing spec 008's SC-012 measure.
- *Compute a second, post-reconciliation rate alongside the raw one.* Rejected. Two numbers both called "the discrepancy rate" is the manual-eyeballing problem this feature exists to remove, reintroduced one layer down.

---

## R3 — Opening a round is gated on completion, and the trigger point is a call site that does not exist yet

**Decision**: `recompute_portal_discrepancy` keeps recording a `DiscrepancyCase` on every submission, but the branch that opens a round and queues a work item moves behind a check that **both** roles have an `AssessorCompletion`. A new recomputation call is added to `complete_unit` ([assessor.py:232-279](../../src/portal/assessor.py#L232-L279)) and to the programmatic completion route.

**Rationale**: FR-DR-008 forbids opening while either assessor is still working; FR-DR-009 requires opening at the moment the second declares. The existing code flags on submission ([discrepancy.py:106](../../src/portal/discrepancy.py#L106)), which is the defect the clarify session found: A answers 140 indicators, B answers 3 and differs on 1, rate is 33%, and the unit's one automatic round is consumed while B still has 137 indicators outstanding.

The important structural consequence: **the last submission is never the trigger**. `complete_unit` refuses to declare while any indicator is outstanding ([assessor.py:248-262](../../src/portal/assessor.py#L248-L262)), so the second completion strictly follows the last submission. Today `complete_unit` writes the declaration and redirects — it never touches the discrepancy engine. Without a new call there, a unit reaches mutual completion above tolerance and nothing opens, ever.

`latest_assessor_completion(session_id, portal_id, role)` takes no `cycle_id`, so the gate fits inside `recompute_portal_discrepancy`'s existing parameter list with no signature change.

**Alternatives considered**: Gating in each caller was rejected — five call sites already exist ([assessor.py:184](../../src/portal/assessor.py#L184), [human.py:93](../../src/api/routers/human.py#L93), [seed.py:151 and :155](../../src/portal/seed.py#L151), plus the two read-only ones), and a rule enforced in five places is a rule that will be enforced in four.

---

## R4 — Per-project tolerance lives on `SurveyCycle`; its history lives in its own table

**Decision**: Add `discrepancy_rate_threshold: float | None = None` to `SurveyCycle`, resolved by a single helper `effective_tolerance(repo, cycle_id, settings)` that falls back to `settings.human_discrepancy_rate_threshold`. Attribution (FR-DR-066) goes in a small append-only `tolerance_changes` table carrying project, previous value, new value, actor, and timestamp.

**Rationale**: `SurveyCycle` already carries per-project configuration (`questionnaire_ref`, `project_type`, `country_set`) and is loaded by every route that needs the tolerance. It is stored as a JSON `data` column ([schema.py:14-18](../../src/shared/persistence/schema.py#L14-L18)), so a new field needs no migration.

The field alone cannot satisfy FR-DR-066, and the reason is worth recording because the code says otherwise. `admin.py` claims append-only superseding at [line 221](../../src/portal/admin.py#L221) (`r.insert_cycle(cycle)  # append-only superseding cycle record`) and again at [line 240](../../src/portal/admin.py#L240). **Both comments are false.** `insert_cycle` is an upsert against a `cycle_id PRIMARY KEY`:

```sql
INSERT INTO survey_cycles (cycle_id, data) VALUES (?, ?)
ON CONFLICT(cycle_id) DO UPDATE SET data = excluded.data, created_at = datetime('now')
```
— [repositories.py:51-57](../../src/shared/persistence/repositories.py#L51-L57)

There is exactly one row per cycle and prior values are destroyed. `get_cycle`'s `ORDER BY created_at DESC, rowid DESC` and `list_cycles`' de-duplication loop ([repositories.py:65-78](../../src/shared/persistence/repositories.py#L65-L78)) are both written as if history existed; they are dead defensive code against a schema that cannot produce a second row. FR-DR-066 needs the previous value, so it needs its own table. The two misleading comments should be corrected in passing — they will mislead the next reader exactly as they nearly misled this design.

**The migration hazard**: every current call site passes `settings.human_discrepancy_rate_threshold` as a literal — [assessor.py:189](../../src/portal/assessor.py#L189), [admin.py:145](../../src/portal/admin.py#L145), [admin.py:337](../../src/portal/admin.py#L337), [human.py:98](../../src/api/routers/human.py#L98), [seed.py:153 and :157](../../src/portal/seed.py#L153). All six must move to `effective_tolerance` **together**. A half-migration produces a unit judged under one tolerance and displayed under another, which is worse than either — and worse than today, where at least the wrong number is consistent. After the change, a grep for `settings.human_discrepancy_rate_threshold` outside `effective_tolerance` should return zero hits; that grep is the completion check.

**Alternatives considered**: A general `project_settings` key-value table was rejected as speculative generality — one setting does not justify a schema for arbitrary settings, and YAGNI applies. Storing the tolerance only in the `tolerance_changes` table and reading the newest row was rejected: every comparison would need an extra query on the hot path for a value that belongs with the project.

---

## R5 — Range validation is genuinely missing, not merely unenforced

**Decision**: Validate `0.0 <= tolerance <= 1.0` at the point of change (FR-DR-064) and add `human_discrepancy_rate_threshold` to `validate_settings`.

**Rationale**: `validate_settings` range-checks `portal_differing_answer_rate_threshold` and `portal_affirmative_rate_gap_threshold` ([validation.py:66-77](../../src/shared/config/validation.py#L66)) but **not** `human_discrepancy_rate_threshold`, even though it was added alongside them ([settings.py:78](../../src/shared/config/settings.py#L78)) with an env override ([settings.py:181-184](../../src/shared/config/settings.py#L181)). `AIQ_HUMAN_DISCREPANCY_RATE_THRESHOLD=50` — the natural mistake, meaning "50%" — is accepted today and silently disables flagging entirely, because `rate > 50.0` is never true. The omission is pre-existing; the per-project setting makes it reachable from the UI, which is what promotes it from latent to worth fixing.

FR-DR-065 (0% honoured, not treated as unset) is why the field is `float | None` rather than `float` defaulting to `0.0`: `None` means inherit, `0.0` means "any disagreement flags". Collapsing them would make a deliberate 0% indistinguishable from an unset project.

---

## R6 — The five badge states are one derived function, used by three consumers

**Decision**: A single `unit_reconciliation_state(repo, session_id, cycle_id, portal_id, settings)` returns the unit's state — `awaiting_second_assessment`, `full_consensus`, `within_tolerance`, `above_tolerance_in_progress`, `reconciliation_open`, `persistent_discrepancy` — along with the rate, the compared count, the disputed set, the tolerance in force, and the rounds consumed. Nothing is stored; it is derived from the rounds table plus a `compute_portal_discrepancy` call.

**Rationale**: Three separate consumers ask overlapping questions: the badge needs five visual states (FR-DR-041), the assessor route needs to know whether to redirect into the workspace (FR-DR-010) or not (FR-DR-035), and publication readiness needs to know whether a round is open (FR-DR-059). Derived three times, these drift, and the drift is invisible: a badge showing "reconciliation open" while the assessor route declines to route there is a bug no test would catch unless it asserted both at once.

Persistent discrepancy is *derived*, not stored, for the same reason spec 008 derived completion (R8 there): storing it would require invalidation on every submission, tolerance change, and joint answer, and a stale flag here routes a real assessor to the wrong screen.

**Alternatives considered**: A stored `unit_discrepancy_state` column refreshed on submission was rejected on invalidation grounds. It is, however, the natural remedy for the badge cost limitation the spec records, and should be revisited if that becomes a real problem rather than a recorded one.

---

## R7 — The Senior Reviewer's two dispositions ride on the existing concurrency guarantee

**Decision**: Both dispositions (FR-DR-055) go through the existing `dispose_escalation` / `record_disposition` path, with `resolution` values `returned_for_reconciliation` and `published_unresolved`. A return additionally opens a new round attributed to that reviewer.

**Rationale**: [`record_disposition`](../../src/shared/persistence/repositories.py#L530-L546) already guarantees exactly one disposition per item under concurrency, enforced by a `UNIQUE` constraint on `escalation_dispositions.item_id` ([schema.py:135-141](../../src/shared/persistence/schema.py#L135)) rather than by a read-then-write. A second concurrent reviewer gets `False`, not a silent overwrite. Two reviewers deciding simultaneously — one returning, one publishing — is exactly the race this feature could otherwise introduce, and the guarantee already exists. Building a second, weaker mechanism beside it would be the worst outcome.

The disposition form already reads dynamically named `resolved__<question_id>` fields off the raw form ([admin.py:400-408](../../src/portal/admin.py#L400-L408)), so per-indicator arbitration needs no new plumbing.

**Consequence to handle**: `dispose_escalation` currently returns `bool` and [admin.py:409](../../src/portal/admin.py#L409) discards it. A `False` return means "someone else already decided" and today produces a redirect indistinguishable from success. With two dispositions that lead to opposite outcomes, that silence stops being acceptable — the return value must be surfaced.

---

## R8 — Publication precedence gains one term and one honest label

**Decision**: `final_answer`'s precedence becomes: Senior Reviewer arbitration → joint answer → A/B agreement → single answer → contested fallback. A companion `final_answer_detail()` returns the value together with the basis that produced it; the publish path records the contested indicator set on the publication record.

**Rationale**: [finalize.py:121](../../src/api/finalize.py#L121) is the integrity hole the spec surfaced as FR-DR-057:

```python
return bool(a.answer)  # unresolved disagreement pending arbitration: best-effort placeholder
```

Assessor A wins, silently, and the docstring three lines above claims the function "never invents an answer nobody gave" — which is true of the value but false of the agreement it implies. FR-DR-057 does not ask for a new tie-break (A5 is explicit that the existing rule stands); it asks that the rule be stated and the result marked contested. That is a labelling change, not an arithmetic one, and the published score is unaffected.

Arbitration outranks a joint answer because a reviewer's per-indicator decision is a later, higher-authority act; FR-DR-051 only requires joint answers to beat the assessors' *own originals*, which this ordering satisfies.

`final_answer` keeps its `bool | None` signature — both publishers call it ([admin.py:368](../../src/portal/admin.py#L368) and the REST publication router) and spec 008's parity guarantee depends on them sharing it. The detail variant is additive.

---

## R9 — Programmatic parity needs one new call and one new read

**Decision**: The programmatic completion route gains the same recomputation call as `complete_unit` (R3), and a new `GET /cycles/{cycle_id}/units/{portal_id}/discrepancy` returns `unit_reconciliation_state`'s output.

**Rationale**: FR-DR-070's parity already half-holds — [human.py:93-99](../../src/api/routers/human.py#L93) recomputes on submission exactly as the portal does. But since R3 moves the trigger to completion, parity now depends on the *completion* route recomputing, and the programmatic one does not. Without it, a unit assessed entirely through the API never opens a round: precisely the bypass FR-DR-070 forbids.

FR-DR-071 has no existing surface at all. Grep confirms discrepancy is imported into `src/api/` in exactly two places — `finalize.py` for `find_resolved_answer` and `human.py` for the recompute — and neither returns state to a caller.

---

## R10 — The engine this feature builds on has no tests

**Decision**: Add `tests/unit/test_portal_discrepancy.py` covering the existing engine's current behaviour **before** changing it, then extend it for the overlay, the completion gate, and the cap.

**Rationale**: `src/portal/discrepancy.py` has no test file. Nothing under `tests/` references `recompute_portal_discrepancy`, `compute_portal_discrepancy`, or `find_resolved_answer`; the only matches for "discrepancy" are in adjudication fixtures and the AI-side tests. The `> threshold` boundary (A2), the `None`-on-no-overlap contract, the idempotency guard, and `find_resolved_answer`'s deliberate newest-item-wins rule ([discrepancy.py:144-149](../../src/portal/discrepancy.py#L144)) are all load-bearing for this feature and all unverified.

R2 modifies `_compare`, which every one of those behaviours flows through. Changing an untested function that four call sites depend on, in the same change that adds the overlay, means a regression and a new feature would be indistinguishable in the diff. Characterisation tests first.

---

## R11 — The new template inherits three hard gates that already fail loudly

**Decision**: The reconciliation workspace template must satisfy the existing quality gates from the start, and its route must be added to the enumerated render test.

**Rationale**: [test_ui_quality_checks.py](../../tests/unit/test_ui_quality_checks.py) enforces three things that will fail a naive new template:

1. **Zero emoji** across every file under `src/portal/templates` ([test:61-86](../../tests/unit/test_ui_quality_checks.py#L61)). The badge's five states must use the existing SVG icon sprite, not characters.
2. **WCAG 2.2 contrast** on colour tokens ([test:113-131](../../tests/unit/test_ui_quality_checks.py#L113)). Five badge states need five token pairs that pass; the available variants are `badge--yes`, `--no`, `--flag`, `--warning`, `--pending`, `--neutral`, `--info`, `--stale`, and others already in the sheet, so no new colour needs inventing.
3. **Semantic landmarks** on every enumerated portal route ([test:205-238](../../tests/unit/test_ui_quality_checks.py#L205)) — skip link, `role="banner"`, `id="main-content"`, `role="contentinfo"`. Extending `base.html` supplies all four.

**The trap worth naming**: that route list asserts HTTP 200. The workspace route must **refuse** a unit with no open round (FR-DR-014), and the `seeded_client` fixture seeds one Assessor A submission and no round at all — so adding the workspace URL to that list naively makes it fail. Either the fixture gains a flagged unit with an open round, or the refusal is asserted as its own case. It must be a deliberate choice, because the failure will look like a routing bug.

---

## R12 — Two pre-existing inconsistencies to note, not to fix

**Decision**: Record both; neither is in scope.

1. **`portal_discrepancy_cases()` cannot see human cases.** It queries `scope="portal"` ([escalations.py:80](../../src/review/escalations.py#L80)) while the human engine writes `scope="portal_human"` ([discrepancy.py:62](../../src/portal/discrepancy.py#L62)). The review view has always returned an empty list for human discrepancies. This feature surfaces human discrepancy through the admin badge and the workspace instead, so nothing regresses — but anyone who assumes that view shows human cases will be wrong, and the near-identical scope strings make the mistake easy.
2. **`DiscrepancyCase.scope`'s docstring is stale.** It reads `# "question" | "portal"` ([entities.py:387](../../src/shared/state/entities.py#L387)); a third value has been written since spec 005. One-word fix, worth doing while the file is open.

Also noted for the record: `list_escalations(unresolved_only=True)` scans every escalation in the session and then every row of `escalation_dispositions` ([repositories.py:511-529](../../src/shared/persistence/repositories.py#L511)), and the idempotency guard runs it on **every submission**. At POC scale this is irrelevant. It is the same growth curve as the badge limitation the spec records, and belongs to the same future optimisation.
