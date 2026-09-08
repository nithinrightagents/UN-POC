# Phase 0 Research: Disagreement Labelling for Human Assessor Discrepancies

**Feature Directory**: `specs/017-disagreement-labelling`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-09-07

Twelve findings. R1, R2 and R5 change the shape of the implementation; R4 contradicted a word in the spec, and the spec has been amended.

---

## R1 — The engine needs no change at all, and that is worth protecting

**Decision**: `src/portal/discrepancy.py` is not modified by this feature. The labelling module imports `_compare` read-only and touches nothing else.

**Rationale**: The spec's entire safety argument (D1, FR-DL-040 to FR-DL-047, SC-002) is that the numeric path is untouched. The strongest available evidence for that claim is a diff that does not include the file. `_compare` already returns `(common, disagreements, rate, flagged)` — the disputed set this feature labels is its second element, available without recomputation. Importing `_compare` from outside the module is established practice: [admin.py:31](../../src/portal/admin.py#L31) and [cycles.py:34](../../src/api/routers/cycles.py#L34) both do it.

**Alternatives considered**: Dispatching from inside `recompute_portal_discrepancy`, which would have given programmatic parity for free. Rejected — that function is called from **ten** sites including three seed scripts, the tolerance-change route ([admin.py:1011](../../src/portal/admin.py#L1011)), and reconciliation close ([reconciliation.py:255](../../src/portal/reconciliation.py#L255)). Labelling would then fire from a tolerance change, which is exactly the class of later event FR-DL-007 forbids. The once-guard would suppress the duplicate, but the design would rest on a guard rather than on the trigger being right.

---

## R2 — The trigger is the second completion declaration, and there are exactly two of them

**Decision**: `dispatch_labelling_pass()` is called from the two completion handlers — [assessor.py:309](../../src/portal/assessor.py#L309) `complete_unit` and [completions.py:42](../../src/api/routers/completions.py#L42) `declare_completion` — immediately after their existing `recompute_portal_discrepancy` call.

**Rationale**: FR-DL-006 says the pass runs "once that unit's assessment submissions are complete". `AssessorCompletion` is precisely that declaration, and the engine already reads both of them at [discrepancy.py:141](../../src/portal/discrepancy.py#L141) for the round gate, so the condition is proven checkable at this point. Two call sites means FR-DL-080 (programmatic parity) is two lines, and both sit in the same position in near-identical code.

**Alternatives considered**: A completion-count trigger inside `Repository.insert_assessor_completion`. Rejected as invisible control flow — a reader of the completion handler would have no way to know a model call had been scheduled.

---

## R3 — The portal cannot call a model synchronously, and does not have to

**Decision**: The two handlers gain `request: Request` and `background: BackgroundTasks`. The dispatch schedules an async `run_labelling_pass()` which opens its own SQLite connection and uses `request.app.state.ai_runtime.provider`.

**Rationale**: Both handlers are sync `def`; `ModelProvider.generate` is async. The precedent exists one file over: [live_prefill.py:25](../../src/portal/live_prefill.py#L25) is an async background runner that "opens its own SQLite connection (the request's connection is closed by the time this runs in the background)" and takes `runtime.provider`. This feature is the same shape with one model call instead of a pipeline. FR-DL-044 (never delay a submission) and D7 (never on a display path) are then satisfied structurally rather than by discipline.

**Alternatives considered**: (a) Converting the handlers to `async def` — a larger blast radius on two routes doing synchronous repository work. (b) `asyncio.run_coroutine_threadsafe` against the app loop — works, but hand-rolls what `BackgroundTasks` already does. (c) A polled worker as the *only* runner — rejected because it makes labels depend on an operator remembering to run something, while FR-DL-008 wants them present by sign-off in the ordinary course. The worker still exists, as R6.

---

## R4 — "Registrable domain" is the wrong comparison for government hosts

**Decision**: Two URLs are the same source when their normalised hosts are equal, **or when one is a dot-boundary suffix of the other**. Normalisation is: lowercase, strip userinfo and port, strip a leading `www.`, strip a trailing dot.

| Pair | Verdict |
|---|---|
| `dvla.gov.uk` vs `hmrc.gov.uk` | different sources |
| `gov.sg` vs `e-services.gov.sg` | same source |
| `www.gov.br` vs `gov.br` | same source |

**Rationale**: The spec (A3, FR-DL-030) says "registrable domain", which means eTLD+1. Applied literally to government hosts it is badly wrong in one direction: `dvla.gov.uk` and `hmrc.gov.uk` share the registrable domain `gov.uk`, so two assessors citing entirely different agency portals would be recorded as having used the same source. It is also unimplementable without a public suffix list — `tldextract` and `publicsuffix2` both fetch or bundle a PSL — and this codebase has taken no new runtime dependency since 001.

The suffix rule needs no dependency, gets the agency case right, and gets the national-portal-versus-subdomain case right, which plain host equality does not.

**The direction of error matters, and this rule errs the safe way.** Declaring "different sources" is an assertion the pre-pass makes on its own authority, which no model reviews. Declaring "same source" merely routes the dispute to the classifier, which can still answer **Not enough notes**. The suffix rule collapses toward "same" in ambiguous cases, so its mistakes cost a model call rather than producing a wrong label.

**This deviated from the spec's wording, and the spec has been amended to match (2026-09-07).** A3, D5 and FR-DL-030 now specify normalised-host comparison with a subdomain treated as the same source as its parent, and FR-DL-030 additionally requires the comparison to resolve toward *same source* where uncertain — making the safe direction of error a requirement rather than an implementation choice.

**Existing helper**: [admissibility.py:32](../../src/shared/tools/linkresolution/admissibility.py#L32) already strips userinfo and port from a netloc. Its logic is reused rather than re-derived; the `www.` and suffix rules are added in the new module, because changing a link-resolution helper for a portal feature would couple two unrelated subsystems.

---

## R5 — Append-only means three tables and no status column

**Decision**: `labelling_passes` (one row per unit, `UNIQUE(session_id, portal_id)`), `disagreement_labels` (append-only, `UNIQUE(pass_id, question_id)`), `labelling_attempts` (append-only, one row per unsuccessful attempt). No row is ever updated. Every state a surface needs is derived.

| State | Derivation |
|---|---|
| Never labelled | no `labelling_passes` row for the unit |
| Awaiting | pass row, no label row, fewer than 3 attempt rows |
| Established | label row exists |
| Attempted and exhausted | pass row, no label row, 3 attempt rows |

**Rationale**: FR-DL-054 says a recorded label is never altered or deleted, and FR-DL-058 requires attempted-and-exhausted to be distinguishable from awaiting. A `status` column would satisfy the second by violating the first — the row would be written `pending` and then updated. Splitting attempts into their own append-only table makes the attempt count a `COUNT(*)`, makes exhaustion derived rather than asserted, and follows the `joint_answers` / `tolerance_changes` precedent exactly ([schema.py:374](../../src/shared/persistence/schema.py#L374), [schema.py:392](../../src/shared/persistence/schema.py#L392)).

The `UNIQUE(session_id, portal_id)` index on `labelling_passes` **is** the FR-DL-007 once-guard — an index rather than a read-then-write check, following the concurrency technique the codebase already uses for dispositions and joint answers.

---

## R6 — A pass that was dispatched but not finished is finished, not re-dispatched

**Decision**: `run_labelling_pass` labels what it can and leaves the rest awaiting. A CLI command, `label-drain`, completes the outstanding disputes of passes already dispatched. It never creates a pass row.

**Rationale**: This is the distinction FR-DL-007 actually draws. Dispatching a *new* pass in reaction to a later event is forbidden; finishing the one pass a unit already has is not a new pass. The distinction matters concretely — without it a single dropped connection at completion time would leave a unit's disputes awaiting forever, while the spec's Known Limitation says permanent blanking follows *three recorded failures*, not zero.

**The corollary is that "no provider" must not record an attempt.** If `ai_runtime` is unset or labelling is disabled, nothing was attempted, so no `labelling_attempts` row is written and the disputes stay awaiting rather than burning toward exhaustion. Recording a failure for a call never made would turn every provider-less test run into permanent exhaustion.

---

## R7 — The model is asked for one enum and two booleans, and never learns who is who

**Decision**: One call per dispute, `response_schema` constrained, `temperature=0.0`. The two positions are presented as "Position 1" and "Position 2", ordered by a role-independent deterministic key (cited URL, then notes, lexicographically). The caller holds the mapping back to roles; the model never receives it.

**Rationale**: `ModelProvider.generate` already accepts `response_schema` and sets `response_mime_type="application/json"` ([llm_factory.py:152](../../src/core/llm_factory.py#L152)), so FR-DL-035 (reject any label outside the applicable set) is enforced by the schema first and re-validated on parse. FR-DL-038 forbids the classifier knowing which position is Assessor A's; ordering by role would leak it through position alone, and random ordering would make the stored input digest unreproducible. A deterministic content-derived order satisfies both.

`NOTES_CONTRADICT_ANSWER` is the only per-side observation needing judgement, so it rides in the same response as two booleans keyed to Position 1 and 2. `NO_NOTES` and `ACCEPTED_AI_UNCHANGED` are read straight off the submission — empty `notes`, and `ai_suggestion_accepted` — with no model involved.

---

## R8 — Three attempts sit above the provider's own retries, which are substantial

**Decision**: `run_labelling_pass` wraps `provider.generate()` in up to three attempts. Each attempt is one full `generate()` call.

**Rationale**: FR-DL-057 says the three attempts are "counted only after the model provider's own handling of transient failures has been exhausted". That handling is not nominal: [llm_factory.py:38](../../src/core/llm_factory.py#L38) retries a 429 at 30/60/90 seconds and a transport error at 2/5/10 seconds before raising. One failed attempt at this layer therefore already represents four rejected calls; three of them is a genuinely dead provider, which is the state FR-DL-058 wants recorded. It also keeps the exhausted state rare enough that the Known Limitation's "permanently blanked" outcome describes a real outage rather than a flaky afternoon.

---

## R9 — Cost attribution needs no new mechanism

**Decision**: `CostLedger.record(stage="disagreement_labelling", ...)` with `estimate_cost(model_identity, in, out)`, on the connection the runner already holds.

**Rationale**: FR-DL-090 requires labelling spend to be attributable and distinguishable from prefill's. `CostLedger.record` takes a `stage` string ([cost_ledger.py:35](../../src/core/telemetry/cost_ledger.py#L35)) and every prefill call already writes its own stage, so a distinct stage value is the whole of the work. FR-DL-091 (what share of disputes needed a model at all) is a count over `disagreement_labels` partitioned on whether the row names a model — which FR-DL-051 already requires it to record.

---

## R10 — The label surfaces are two existing templates and one new route

**Decision**: `admin_escalations.html` renders a badge per disputed indicator (its dispute list is already there, [admin_escalations.html:80](../../src/portal/templates/admin_escalations.html#L80)). `admin_project_detail.html` gains a per-unit label composition. A new Administrator route carries the cross-project ambiguity measure. `assessor_reconcile.html` and `assessor_unit.html` are **not** touched.

**Rationale**: `admin_escalations.html` describes itself as the "Senior Reviewer arbitration workspace for resolving disagreements", which is exactly where FR-DL-060 puts the label. FR-DL-065 forbids it on assessor surfaces, and the strongest form of that guarantee is that the two assessor templates do not appear in the diff — backed by a test asserting their rendered output contains no label text.

---

## R11 — The measure needs a cross-cycle read, which no repository method currently offers

**Decision**: One new repository method aggregating `disagreement_labels` by question, optionally filtered to a cycle. The per-cycle and cross-cycle views (FR-DL-075) are the same query with and without the filter.

**Rationale**: Every existing discrepancy read is scoped to one unit or one session, because until now disagreement was only ever aggregated per unit — precisely the gap the spec names. The cross-cycle view is also the FR-DL-067 scope boundary in practice: the filtered call backs the Senior Reviewer's project page, the unfiltered one backs the Administrator route. The boundary is which route calls which, and it is presentational only, as the spec's Known Limitation states.

**Note on question identity**: `Question` is `cycle_id`-bound with no cross-edition identity, so the cross-cycle measure aggregates on `indicator_id` where present and falls back to `question_id`. Two cycles of the same questionnaire roll up together only to the extent their `indicator_id` values match — a limitation of the existing data model, not something this feature can fix.

---

## R12 — The engine's behaviour under a joint answer is already correct here

**Decision**: No special handling. `_compare` skips any question carrying a joint answer, so a dispute resolved before the pass runs is simply not in the disputed set.

**Rationale**: [discrepancy.py:52](../../src/portal/discrepancy.py#L52) filters joint-answered questions out of `disagreements` before returning. The spec's edge case — a dispute resolved by a joint answer before the pass runs "ceases to exist and no label is produced" — is therefore inherited behaviour rather than implemented behaviour. And because the pass runs at completion, before any reconciliation round can have produced a joint answer, the ordinary case is that every disagreement is present and labelled.
