# Contract: The Labelling Pass

**Module**: `src/portal/disagreement_labels.py` (new)
**Requirements**: FR-DL-001 to FR-DL-008, FR-DL-030 to FR-DL-032, FR-DL-040 to FR-DL-047, FR-DL-050 to FR-DL-059, FR-DL-092

---

## 1. Dispatch

```python
def dispatch_labelling_pass(
    repo: Repository,
    settings: Settings,
    session_id: str,
    cycle_id: str,
    portal_id: str,
    question_ids: list[str],
    threshold: float,
    dispatched_by: str,             # 'portal' | 'api' | 'cli'
    provider_available: bool,
) -> LabellingPass | None:
```

Synchronous, cheap, writes at most one row. Returns the pass when one was created, `None` in every skip case.

**Preconditions, in order. The first that fails returns `None` and writes nothing:**

| # | Condition | Why |
|---|---|---|
| 1 | `settings.disagreement_labelling_enabled` | operator switch |
| 2 | `provider_available` | R6 — no provider means no pass, not an exhausted one |
| 3 | both roles have an `AssessorCompletion` for the unit | FR-DL-006 |
| 4 | `_compare(...)` returns a non-`None` result | nothing comparable yet |
| 5 | `disagreements` is non-empty | nothing to label |
| 6 | the `INSERT` succeeds | FR-DL-007, via `idx_labelling_pass_once` |

Condition 6 is an insert attempt, not a lookup. `sqlite3.IntegrityError` is caught and returns `None` — that is the once-guard doing its job, not an error.

**`_compare` is called read-only.** No `DiscrepancyCase` is written, no escalation is queued, no round is opened. The disputed set is copied into `data.disputed_question_ids` and everything downstream reads that copy (FR-DL-042).

**Call sites — exactly two, both immediately after the existing `recompute_portal_discrepancy`:**

| Site | Adds |
|---|---|
| [assessor.py:357](../../../src/portal/assessor.py#L357) `complete_unit` | `request: Request`, `background: BackgroundTasks`, `dispatched_by="portal"` |
| [completions.py:116](../../../src/api/routers/completions.py#L116) `declare_completion` | `request: Request`, `background: BackgroundTasks`, `dispatched_by="api"` |

`provider_available` is `getattr(request.app.state, "ai_runtime", None) is not None`. When a pass is created, `background.add_task(run_labelling_pass, ...)` is scheduled with the database path and the runtime — never with the request's repository, whose connection is closed by then (R3).

**Neither handler's response depends on any of this.** A raised exception inside dispatch is caught and logged; the completion is already recorded and the redirect or response is unchanged (FR-DL-043, FR-DL-044).

---

## 2. The runner

```python
async def run_labelling_pass(
    database_path: str,
    settings: Settings,
    runtime: AIRuntime,
    pass_id: str,
) -> LabellingPassResult:
```

Opens its own connection, resolves the pass, and processes each outstanding dispute. Idempotent and resumable: it skips any dispute that already has a label row or already has three attempt rows, so a second run over the same pass is safe and is exactly what `label-drain` does.

Per dispute:

```
1. load A's and B's latest submissions for the question
2. observations := deterministic per-side observations (NO_NOTES, ACCEPTED_AI_UNCHANGED)
3. label := classify_deterministically(a, b)
4. if label is not None:
       write disagreement_labels row, established_by='deterministic', no model named
       continue                                            # FR-DL-031, FR-DL-032, SC-009
5. if attempts_so_far(pass_id, question_id) >= 3:
       continue                                            # FR-DL-057 cap
6. call the classifier                                     # see classifier-contract.md
7. on success:  write disagreement_labels row, established_by='classifier'
   on failure:  write one labelling_attempts row
8. record cost against stage 'disagreement_labelling'      # FR-DL-090
```

**One attempt per dispute per run.** A failure writes a single attempt row and moves on rather than retrying in a tight loop — the provider has already exhausted its own 30/60/90s and 2/5/10s backoffs before raising (R8), so an immediate retry would fail the same way and waste the cap. The remaining attempts are consumed by later runs.

**Failure of one dispute never stops the pass.** Every exception is caught per dispute.

---

## 3. The deterministic pre-pass

```python
def normalise_host(url: str | None) -> str
def same_source(url_a: str | None, url_b: str | None) -> bool
def classify_deterministically(a, b) -> DisagreementLabel | None
```

Pure functions, no repository, no I/O — directly unit-testable, which is where the table of cases in [quickstart.md](../quickstart.md) Scenario 2 points.

Rules and rationale are in [data-model.md](../data-model.md) §7 and [research.md](../research.md) R4. The one behaviour worth restating: **an unparseable URL is treated as no evidence cited**, so a dispute where one side cited garbage and the other cited nothing is `NOT_ENOUGH_NOTES` territory rather than `ONE_FOUND_NOTHING`, because neither host survives normalisation.

---

## 4. State projection

```python
def unit_labelling_state(repo, session_id, portal_id) -> dict[str, DisputeLabelState]
```

One reader for every surface. Returns, per disputed question id:

```python
@dataclass(frozen=True)
class DisputeLabelState:
    question_id: str
    state: str                          # 'never_labelled' | 'awaiting' | 'established' | 'exhausted'
    label: DisagreementLabel | None
    badge: str | None                   # "Judged differently", etc.
    observations: dict[str, list[SideObservation]]
    stale: bool                         # current submissions differ from those labelled (FR-DL-068)
    record: DisagreementLabelRecord | None
```

`stale` compares the stored `submission_ids` against the unit's current latest submissions. `state` derivation is in [data-model.md](../data-model.md) §3.

**This function makes no model call and writes nothing** (FR-DL-045). It is safe on any GET path, which is the property `compute_portal_discrepancy` has and `recompute_portal_discrepancy` does not — and the reason both exist.

---

## 5. Counts for observability

```python
def labelling_counts(repo, cycle_id: str | None = None) -> LabellingCounts
```

Returns `awaiting`, `exhausted`, `established_deterministic`, `established_by_classifier` (FR-DL-091, FR-DL-092). A rising `awaiting` is what a provider outage looks like from the outside; a rising `exhausted` is what it looks like after three attempts each.

---

## 6. CLI

```
aiq label drain [--cycle CYCLE_ID] [--limit N]
```

A `click` group named `label` with one `drain` command, on the `telemetry` group's shape ([cli.py:547](../../../src/cli.py#L547)) and reached through the `aiq` console script. Completes outstanding disputes of passes that already exist. **It never creates a pass row** — a unit that was never dispatched stays never labelled, which is what the spec's "enabled part-way through a cycle" edge case requires.

Reports counts before and after. Exits non-zero only on a configuration error, never on labelling failures, which are data.

---

## 7. What this module must never do

Stated as prohibitions because each has a test:

- Never import from or write through `recompute_portal_discrepancy`.
- Never write a `DiscrepancyCase`, `EscalationQueueItem`, `ReconciliationRound` or `JointAnswer`.
- Never issue `UPDATE` or `DELETE` against any of its three tables.
- Never be called from a GET handler.
- Never raise into a request handler.
- Never pass `Prefill.answer`, `Prefill.justification`, `ai_suggested_answer`, a role, or an actor id to the classifier.
