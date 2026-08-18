# 006 — Full MSQ Questionnaire (157 indicators, 6 modules)

**Status:** Done (completed within the same session as 005's workflow platform work)
**Supersedes scope framing in:** 001-ekap-aiq-assessment/poc-question-set.md
(not its code, and not that file's own content — see "What this does not do"
below)

## 1. What changed

001's proof of concept scoped itself to **one** UN E-Government Survey
module: Module 2.1 — Institutional Framework, 16 question rows / 26
indicator IDs (`specs/001-ekap-aiq-assessment/poc-question-set.md` line 5:
"The proof of concept assesses **only** this question set"). That file's
"Unit volume" table sized the whole PoC around that number: 5 countries x 26
questions x 2 agents = 260 agent runs, ~260 verification fetches. That
26-indicator set survives intact as the "Institutional Framework" module
below — nothing in it was replaced, it was joined by five more modules.

The running questionnaire is now the **full UN OSI Questionnaire**, all 6 modules, 111+
indicators total, loaded from `data/questionnaires/templates/un_osi_2024_master.json`:

| Module | Indicators |
|---|---|
| Institutional Framework | 26 |
| Content Provision | 8 |
| Service Provision | 30 |
| Technology | 14 |
| E-Participation | 20 |
| E-Government Literacy | 13 |
| **Total** | **111** |

`portal/seed.py`'s demo seed and the live `data/aiq.db` were both reseeded
against this file (`aiq seed demo`) in place of the old 10-question
placeholder set that predated even 001's 26-indicator scope.

## 2. Why

This followed directly from 005's workflow platform: 005 re-scoped the
product from "5-country AI proof of concept" to the full admin/two-human-
assessor/MSQ-ingestion/public-KB workflow engine Deniz described. Restricting
the live indicator set to one module out of six was a leftover from 001's
narrower demo, not a decision anyone made for 005's product. Once the admin
surface (005 §3.2) lets an operator create a real project against a real
MSQ upload (005 §3.5), the assessed indicator set has to be the MSQ's actual
full indicator set, not a 26-row subset chosen for a procurement-board demo.

## 3. What this does not do

`specs/001-ekap-aiq-assessment/poc-question-set.md` is left **unedited**. It
remains an accurate historical record of what the original 001 PoC scoped
itself to and why (it explains the *rationale* for the 26-indicator subset,
which is still true of that original decision — it just no longer describes
the indicator set the running app assesses). Anyone reproducing 001's
original scenarios from that document's steps should still get the
originally-documented behavior for that spec's own test fixtures; only the
live application's data (`data/aiq.db`, `portal/seed.py`) moved to the full
set, per the same "supersede the framing, not the file" convention this repo
already established in 005's own header.

This also does not change unit-volume economics narratively fixed elsewhere
(e.g. 005 §4's "8 seeded portals" demo scale) beyond the obvious: a live run
against the full indicator set is ~6x the per-portal agent-call volume
001's own 26-question sizing assumed, which is exactly why 005's admin
"Run AI Assessment" trigger was built as a background job with a status view
rather than a synchronous request (see `specs/005-un-ekap-platform/spec.md` §2
and `src/portal/live_prefill.py`) — at 100+ questions x N>=2 agents per unit,
a synchronous request-response cycle was never viable.

## 4. Reused unchanged

`shared/state/entities.py`'s `Question`/indicator model needed no schema
change — `un_osi_2024_master.json` fits the same shape 001's 26-row set used
(`question_id`, `indicator_id`, `text`, `answer_type`, `evidence_locus`,
`module`). This is a data-scope change, not a code change.
