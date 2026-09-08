# Contract: Surfaces, Measures and Programmatic Parity

**Requirements**: FR-DL-060 to FR-DL-068, FR-DL-070 to FR-DL-075, FR-DL-080, FR-DL-081, FR-DL-090 to FR-DL-092

---

## 1. Where labels appear, and where they must not

| Surface | Audience | Change |
|---|---|---|
| `admin_escalations.html` | Senior Reviewer | badge per disputed indicator, per-side observations, provenance on demand |
| `admin_project_detail.html` | Senior Reviewer | per-unit label composition beside the existing discrepancy badge |
| `/admin/projects/{cycle_id}/ambiguity` | Senior Reviewer | per-project ambiguity measure (new) |
| `/admin/indicators/ambiguity` | Administrator | cross-project ambiguity measure (new) |
| `GET /api/.../labels` | programmatic | labels, observations, provenance |
| **`assessor_reconcile.html`** | **assessors** | **none — must not change** |
| **`assessor_unit.html`** | **assessors** | **none — must not change** |

**On the per-project route**: a project is a `cycle_id` and lives under `/admin/projects/{cycle_id}` ([admin.py:355](../../../src/portal/admin.py#L355)); `/admin/questionnaires/{set_id}` is the *indicator set*, keyed by set id, not by cycle. The ambiguity route is therefore a sibling of the existing escalations route ([admin.py:1015](../../../src/portal/admin.py#L1015)), not of the questionnaire one. Corrected 2026-09-07.

The last two rows are FR-DL-065 and are enforced by a test that renders both templates for a unit with established labels and asserts no badge string appears in the output. They are also, deliberately, absent from the diff.

---

## 2. How a label is presented

**FR-DL-063 — description, never recommendation.** The badge is the plain-English phrase and nothing else. No colour ranking that implies severity, no ordering that implies priority, no wording that suggests an action. "Judged differently" is a statement about the pair; "One couldn't access" names a circumstance, not a fault.

**FR-DL-062 — per-side observations sit against their side**, in the column already showing that assessor's answer and evidence, never in the pair-level row.

**FR-DL-064 — absence is stated plainly**, and the four states are visibly distinct:

| State | Rendering |
|---|---|
| `established` | the badge |
| `awaiting` | "Labelling not yet complete" |
| `exhausted` | "Labelling was attempted and could not be completed" |
| `never_labelled` | "Not labelled" |

`awaiting` and `exhausted` must not collapse into one string — a temporary state read as permanent is the misreading FR-DL-058 exists to prevent.

**FR-DL-068 — a stale label says so.** Where `DisputeLabelState.stale` is true, the badge is accompanied by "submission has changed since labelling". The label is still shown; it is history, honestly dated.

**FR-DL-050 — provenance is reachable from every badge**: model identity or "established without a model", prompt version, input digest, and time.

---

## 3. The ambiguity measure

```python
def indicator_ambiguity(repo, cycle_id: str | None = None) -> list[IndicatorAmbiguity]

@dataclass(frozen=True)
class IndicatorAmbiguity:
    indicator_key: str          # indicator_id where present, else question_id (R11)
    judged_differently: int     # DIFFERENT_JUDGEMENT count
    units_measured: int         # units contributing at least one labelled dispute
    units_total: int            # units whose pass ran
    labelled_share: float       # proportion of disputes labelled at all
```

**FR-DL-071 — every other label is excluded.** Only `DIFFERENT_JUDGEMENT` counts. Access failures, different sources, and unlabelled disputes must not inflate the figure, or the measure stops meaning "this question is ambiguous" and starts meaning "this question caused trouble".

**FR-DL-072 / FR-DL-073 — the base is always stated.** `units_measured` and `labelled_share` are rendered with the count, never behind a tooltip. A ranking computed over a third of a cycle is legitimate and must look like what it is.

**FR-DL-075 — the same function, two callers.** `cycle_id` set backs the Senior Reviewer's project route; `cycle_id=None` backs the Administrator route. That is the whole of the scope distinction, and it is presentational: nothing prevents a request to the unfiltered route, as the spec's Known Limitation records.

**FR-DL-074 — the insufficient-notes proportion** is reported on the same routes: the share of a cycle's disputes labelled `NOT_ENOUGH_NOTES`. This is the number that decides whether notes should become mandatory, so it is presented as a headline figure rather than a footnote.

---

## 4. Programmatic parity

**FR-DL-080** is satisfied at dispatch: `declare_completion` calls `dispatch_labelling_pass` with the same arguments as `complete_unit`, differing only in `dispatched_by`. A test declares completion for one unit through the portal and another through the API and asserts both produce identical pass and label rows.

**FR-DL-081** — new read-only endpoints:

```
GET /api/cycles/{cycle_id}/units/{portal_id}/labels
    → [{question_id, state, label, badge, observations{A,B}, stale,
        provenance{established_by, model_identity, prompt_version,
                   input_digest, created_at}}]

GET /api/cycles/{cycle_id}/indicator-ambiguity
    → [IndicatorAmbiguity]

GET /api/labelling/counts?cycle_id=...
    → {awaiting, exhausted, established_deterministic, established_by_classifier}
```

All three are pure reads over the projection in [labelling-pass.md](./labelling-pass.md) §4 and §5. **None of them may create a record or invoke a model** (FR-DL-045) — the mistake `compute_portal_discrepancy` exists to prevent, repeated here for the same reason.

The counts endpoint is FR-DL-092: a provider outage shows as a rising `awaiting`, then as a rising `exhausted`, rather than as labels quietly missing.

---

## 5. Sign-off is untouched

**FR-DL-066 is a negative contract and is tested as one.** `publication_readiness` ([finalize.py:39](../../../src/api/finalize.py#L39)) and every disposition path gain no term, no gate, and no reference to labelling. A unit whose disputes are all `exhausted` signs off exactly as one whose disputes are all labelled.

The test asserts this by construction: two units identical but for labelling state produce byte-identical readiness output.
