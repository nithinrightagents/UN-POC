# EKAP Demo Walkthrough

A stage-by-stage click script for demonstrating the full project lifecycle:
questionnaire authoring → unit setup → assessor assignment (lock) → blind
A/B assessment → automatic discrepancy detection → reconciliation →
Senior Reviewer arbitration → publish → public scorecard.

Stage 0 is performed **live** against a brand-new project, so the audience
watches the lock actually take effect. Stages 1-6 open **pre-seeded**
projects that are already frozen at each state of the lifecycle, so you
don't have to hand-type dozens of indicator answers live — each one already
carries two demo assessor emails and is already locked, exactly as it would
be if an admin had really assigned it.

## One-time setup

```bash
aiq db init
aiq seed lifecycle-demo   # creates demo-stage1 .. demo-stage6 (safe to re-run)
aiq serve
```

`aiq seed lifecycle-demo` is a no-op for any `demo-stageN` cycle that
already exists, so it's safe to run again before every demo session.

Demo assessor identities used throughout (shown on every locked project's
"Assessors Assigned" card, and worth reading aloud at least once):

| Role | Demo email |
|---|---|
| Assessor A | `assessor.a@ekap-demo.org` |
| Assessor B | `assessor.b@ekap-demo.org` |

---

## Stage 0 — Build a project, then assign & lock it (live)

Everything in this stage happens on a **new** project you create during the
demo — this is the only stage that isn't pre-seeded, because it's the one
whose entire point is showing edits succeed *before* assignment and get
refused *after*. Stages 1-6 below are pre-seeded as `demo-stage1` ..
`demo-stage6`.

### 0.1 — Tour questionnaire management

1. Nav bar → **Admin** → **Manage Questionnaires**.
2. Point out the stat row (Master Templates / Custom Indicator Sets /
   Thematic Modules) and the catalog table — master templates are tagged
   **Protected** (no delete button); anything under **Custom Set** has a
   **Delete** button because it was branched from a real project by an
   admin (this callback matters later in 0.3).
3. Click **View Indicators** on `un_osi_2024_master` to show the full
   157-indicator What/Why/How structure read-only.

### 0.2 — Create the project

1. Back on **Admin**, fill in **Create New Survey Project**:
   - Project Identifier: `demo-live-<anything>`
   - Display Name: anything descriptive
   - Assessment Scope: **National Online Service Index**
   - Questionnaire: `un_osi_2024_master`
2. Submit → lands on **Manage Workspace** for the new project. Note that
   all 193 UN member states are already tagged as units — creation
   auto-tags every country rather than making you hand-pick up front.

### 0.3 — Show unit add/remove

1. Scroll to **Monitored Units** — check a couple of boxes, use **Remove
   Selected Units** (bulk bar) to prune the list down to 2-3 countries.
2. Scroll to **Bulk Add Countries** — search, select one removed country
   back, **Add N Selected Countries**.
3. Scroll to **Register Target Unit** — add one unit by hand with a custom
   display name and portal URL.

### 0.4 — Show indicator add/remove

1. Scroll to **Indicators** → **Add New Indicator (What, Why, How)** →
   fill Identifier/Title/Module/Evidence Locus/What/Why/How → submit.
   Point out the blue notice above the form: this doesn't touch the
   master template, it branches a new **Custom Questionnaire Set** (this
   is the thing that then shows up under **Custom Set** back on
   `/admin/questionnaires`, tying back to 0.1).
2. In the indicator table, **Retire** the indicator you just added, then
   **Reactivate** it — point out the status badge flips live.
3. Optional: **Upload Indicator PDF (Auto-Ingest for Review)** with a
   sample module PDF → redirects to **Review Pending Indicators** →
   Approve one candidate, Bulk Reject the rest. This is the AI-assisted
   ingestion path; everything lands in a review queue, nothing is
   auto-added to the live questionnaire.

### 0.5 — Assign assessors → watch it lock

1. Scroll to the **Assign Assessors** card (above Indicators).
2. Enter `assessor.a@ekap-demo.org` / `assessor.b@ekap-demo.org` →
   **Assign & Lock**.
3. The page redirects back showing a **Locked** badge and both emails.
   Scroll down: the **Add New Indicator** form, **Upload Indicator PDF**
   form, bulk indicator actions bar, **Bulk Add Countries** card,
   **Register Target Unit** card, and every unit's **Remove Unit** button
   are all gone — replaced with "Project is locked -- unassign assessors
   to edit" messages.
4. Prove it server-side, not just client-side: open dev tools / a second
   tab and POST directly to `/admin/projects/<id>/units` (or just note
   that the buttons are gone because the routes themselves now redirect
   with `?lock_error=1` — see `admin.py::_blocked_if_locked`).
5. Click **Unassign & Reopen Setup** → confirm the forms reappear → this
   is the deliberate escape hatch for a mistyped email, not a everyday
   button.
6. Point out what's *deliberately* still editable while locked (scroll
   further): the **MSQ PDF** upload per unit, **Project Tolerance**, the
   **Publish** button, the **Discrepancy & Arbitration Queue**, and
   **Delete Project** in the Danger Zone. The lock only freezes the two
   things that would silently corrupt the discrepancy math if changed
   mid-assessment: the unit list and the indicator set.
7. Re-lock it (re-enter the two emails) before moving on, so Stage 0
   ends in the same "locked, awaiting assessment" state as Stage 1 below
   — this is the live version of what `demo-stage1` already models.

---

## Stage 1 — Assigned, Awaiting Assessment (`demo-stage1`)

`/admin/projects/demo-stage1` — Kenya, 20-indicator slice, locked, zero
submissions from either assessor.

- Point out the **Locked** badge and both demo emails are present even
  though nobody has answered a single question yet — locking happens the
  instant assignment happens, not on first submission.
- Open the assessor workspace as Assessor A:
  `/assessor/demo-stage1/<portal_id>?role=A&actor_id=assessor.a@ekap-demo.org`
  (get `<portal_id>` from the unit card, or just go to nav → **Assessor**
  → pick Kenya → **Open as Assessor A**, then add
  `&actor_id=assessor.a@ekap-demo.org` to the URL, or type it into the
  **Assessor Identifier** field before submitting your first answer).
- Answer one or two indicators to show the form (Yes/No, evidence URL,
  notes) and the auto-advance-to-next-unanswered behavior. Don't complete
  the full 20 here — that's already done for you in later stages.

---

## Stage 2 — One Assessor In Progress (`demo-stage2`)

`/admin/projects/demo-stage2` — Brazil. Assessor A has declared complete
(20/20); Assessor B is 12/20 in, already disagreeing on 2 of those 12.

- On **Manage Workspace**, the unit card's **Assessor Declarations** box
  shows Role A: **Complete**, Role B: **Declared? No — Undeclared
  (12/20)**.
- Point out the discrepancy badge is *not* flagging yet, even though the
  12-answered subset already disagrees above tolerance (~17% > 5%) — a
  round only opens once **both** roles have declared, so a partial
  assessor can't trip a false alarm.
- Open as Assessor B (`role=B&actor_id=assessor.b@ekap-demo.org`) and
  finish the remaining 8 indicators, then **Declare Complete** — this is
  the natural bridge into Stage 5/6's discrepancy states if you want to
  drive one live instead of only viewing the pre-baked ones.

---

## Stage 3 — Full Consensus (`demo-stage3`)

`/admin/projects/demo-stage3` — Denmark. Both assessors complete, 0%
disagreement.

- Discrepancy badge reads clean/consensus. This is the "boring" success
  case — worth 10 seconds, then move on.

---

## Stage 4 — Within Tolerance (`demo-stage4`)

`/admin/projects/demo-stage4` — Vietnam. Both complete, 1/20 disagree
(5% — exactly the default tolerance).

- Badge distinguishes this from Stage 3's zero-disagreement case: some
  disagreement exists but it's within the configured tolerance, so no
  reconciliation round opens. Good moment to open **Project Tolerance**
  (still editable while locked) and show that tightening it below 5%
  would immediately open a round on this exact unit.

---

## Stage 5 — Reconciliation Open (`demo-stage5`)

`/admin/projects/demo-stage5` — Peru. Both complete, 2/20 disagree (10% >
5%) — crossed the threshold on the second completion, so an automatic
round opened on its own.

- Unit card shows the **Persistent Discrepancy / reconciliation** panel
  with the still-contested indicator table (Assessor A / Assessor B /
  Joint Settlement columns).
- Open the reconciliation workspace as either assessor:
  `/assessor/demo-stage5/<portal_id>/reconcile?role=A&actor_id=assessor.a@ekap-demo.org`
  — each disputed indicator shows both sides' answer, evidence, and notes
  side by side (not blind anymore — this is the arbitration phase) and a
  **Commit Joint Answer** form requiring a written justification.
- Commit a joint answer on one disputed indicator to show the round
  closing indicator-by-indicator as both sides converge.

---

## Stage 6 — Persistent Discrepancy → Senior Reviewer Arbitration (`demo-stage6`)

`/admin/projects/demo-stage6` — Nigeria. Both complete, 3/20 disagree
(15%). The automatic round ran its course without full resolution and was
force-closed **exhausted** — the one-round-only rule.

- `/admin/projects/demo-stage6/escalations` — **Discrepancy & Arbitration
  Queue**. Shows the escalation item with the differing-answer rate, and
  for each disputed indicator a **"What Each Assessor Entered"** panel —
  Assessor A's and Assessor B's actual answer, evidence link, and notes
  side by side, so the reviewer isn't deciding blind.
- The **Arbitration Resolution Method** dropdown has just two options:

  | Resolution Method | What it does |
  |---|---|
  | **Return to Assessors for another reconciliation round** | Requires a non-empty **Notes** field (the stated reason), then calls `open_reviewer_round()` to reopen a live round on the unit — Assessors A/B get another pass in the reconciliation workspace. Nothing publishes yet. |
  | **Senior Reviewer reviews both entries and decides Yes/No** | Requires a Yes/No selection for **every** disputed indicator (enforced server-side — [admin.py](src/portal/admin.py), the dispose route rejects the submission otherwise) after reading the A/B comparison panel above. Those answers become `resolved_answers` on the disposition, and `find_resolved_answer()` returns them first at publish time, ahead of any joint-workspace or A/B-consensus answer ([finalize.py:148-153](src/api/finalize.py#L148-L153)). |

  For this demo, pick **Senior Reviewer reviews both entries and decides
  Yes/No**, read the A/B comparison for each of the 3 disputed
  indicators, select a final Yes/No for each, add arbitration notes,
  submit.
- Point out the item now shows **Arbitrated & Resolved** with the
  recorded disposition and final answers — this is exactly what
  `final_answer_detail()` will read back at publish time (Stage 7),
  taking precedence over both assessors' original submitted answers.
- Note: `reconciled_by_joint_review` can still appear on an item's
  disposition even though it's not a dropdown option — the system writes
  it automatically ([reconciliation.py:324-334](src/portal/reconciliation.py#L324-L334))
  when a reconciliation round closes because the assessors themselves
  converged on every disputed indicator via joint answers, with no
  Senior Reviewer action at all.

---

## Stage 7 — Publish & Public Scorecard

Use `demo-stage3` or `demo-stage4` (already clean) — or `demo-stage6`
right after arbitrating it in Stage 6, to show a contested unit can still
publish once resolved.

1. On **Manage Workspace**, click **Senior Reviewer: Publish Score** on
   the unit (disabled with a tooltip if readiness isn't met — point that
   out on an unfinished unit like `demo-stage1` or `demo-stage2` first,
   then click the real one).
2. Nav bar → **Public** → the cycle now appears in the public index →
   open the ranking table → open the unit's public scorecard
   (`/public/<cycle_id>/<portal_id>`) → shows the published score and
   per-indicator breakdown, sourced from the same `PublicationRecord` row
   an admin just wrote — no export/import step in between.

---

## Appendix

### What the lock does and doesn't touch

Once `assign-assessors` is submitted, `SurveyCycle.status` flips to
`"locked"` and these routes refuse (redirect with `?lock_error=1`,
`admin.py::_blocked_if_locked`):

- Add / remove / bulk-add / bulk-remove units
- Add / edit / retire / reactivate / bulk-retire / bulk-reactivate
  indicators
- PDF indicator ingestion and pending-indicator approve/reject/bulk-reject

Deliberately **not** locked (per-unit MSQ upload, publish, and project
administration stay available throughout assessment):

- MSQ PDF upload per unit
- Project tolerance threshold
- Publish
- Discrepancy & Arbitration Queue (dispose escalation)
- Delete Project

### Stage → URL cheat sheet

| Stage | Cycle ID | Admin workspace |
|---|---|---|
| 0 | *(created live)* | `/admin/projects/<your-new-id>` |
| 1 | `demo-stage1` | `/admin/projects/demo-stage1` |
| 2 | `demo-stage2` | `/admin/projects/demo-stage2` |
| 3 | `demo-stage3` | `/admin/projects/demo-stage3` |
| 4 | `demo-stage4` | `/admin/projects/demo-stage4` |
| 5 | `demo-stage5` | `/admin/projects/demo-stage5` |
| 6 | `demo-stage6` | `/admin/projects/demo-stage6` &nbsp;·&nbsp; `/admin/projects/demo-stage6/escalations` |

Re-seeding: `aiq seed lifecycle-demo` never overwrites a cycle that
already exists, so if you commit an answer live during Stage 1/2 and want
a clean copy back, delete that one cycle from **Admin** (Danger Zone →
Delete Project Permanently) and re-run the seed command.
