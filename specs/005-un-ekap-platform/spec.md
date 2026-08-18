# 005 — UN EKAP Assessment & Workflow Engine

**Status:** Completed (2026-08-17)
**Supersedes scope framing in:** 001-ekap-aiq-assessment (not its code — extends it)

## 1. Why this platform extension

001-ekap-aiq-assessment builds exactly the "AI test on 5 sample countries" that
Deniz Susar (UN DESA) described as a **low-effort proof of concept to show the
procurement board** — not the product he actually wants built. Re-reading the
scope-meeting transcript (`understanding docs/UN_Project_Scope_Meeting_Transcript_Compacted.md`)
and project context notes against what exists in `src/` surfaces a real gap:

| Deniz asked for | What 001 built | Gap |
|---|---|---|
| Admin portal to spin up projects (UN E-Gov 2026, LOSI UK 2025), set indicators, assign unit URLs | CLI-only (`aiq question add`), no project creation UI, no unit/URL admin UI | No admin surface |
| 2 blind human assessors per country score independently, paste evidence URLs | `AssessorAgentRun` models **AI agents** (agent_index 0..N) reaching AI-vs-AI consensus; one downstream human "reviewer" approves/edits/overrides the AI consensus | No concept of two independent *human* assessors at all |
| Discrepancy check between Assessor A and B at >5%, escalate to arbitration, then Senior Reviewer | Discrepancy/escalation domain logic exists (`DiscrepancyCase`, `EscalationQueueItem`, `portal_differing_answer_rate_threshold`) but is wired to **AI agent pairs**, not human A/B | Right mechanism, wrong inputs |
| MSQ ingestion (50+ page government questionnaire) as assessor context | `MSQLinkCandidate` entity exists as a stub for link candidates only — no document upload/parse | No ingestion pipeline |
| Public knowledge base: rankings, country profiles, LOSI city tables, one-click publish on sign-off | Nothing — today's web app is internal-only (`review/web`) | Doesn't exist |
| AI as human-in-the-loop accelerator (pre-fill + evidence), never autonomous | AI *is* the primary answer producer (adjudicated consensus), human only edits/overrides after the fact | Inverted: UN EKAP makes AI a suggestion layer under two humans, not the decision-maker humans check |

**Decision:** keep the 001 substrate (entities, append-only persistence,
FastAPI + Jinja2 review surface, discrepancy/escalation domain logic, CLI) and
extend it, rather than rewrite. It is a legitimate foundation for the product,
not a throwaway PoC — see `README.md` and `specs/001-ekap-aiq-assessment/`.

## 2. Forced substitution: no LLM access this session (superseded — see below)

This section originally documented a real constraint at the time 005 was
started: this environment had no Gemini/Vertex credentials available, so the
AI pre-fill layer (`src/agents/prefill/heuristic.py`) was a **rule-based
checker that makes real HTTP requests against real government portals** —
HTTPS enforcement, sitemap.xml, privacy-policy link, social-media presence,
and weak language/responsive-design proxies. That covers 6 of the real MSQ's
157 indicators (see `specs/006-full-msq-questionnaire/spec.md`); the rest got
a zero-confidence dummy placeholder. Per explicit instruction, **no Drupal/CMS
integration is in scope either** — the tech stack stays exactly what 001
already uses (Python, FastAPI, Jinja2 server-rendered HTML, SQLite, `click`
CLI).

**Later in the platform execution window, this constraint no
longer holds**: GCP Application Default Credentials were configured for
Vertex AI, and `src/portal/admin.py`'s "Run AI Assessment" action now
dispatches 001's real pipeline — link resolution (prior-survey KB → MSQ →
internet search, `shared/tools/linkresolution/chain.py`) into N ≥ 2
independent live Vertex AI assessor agents, a validator, and an adjudicator
(`orchestration/scheduler.py`) — as a background run per unit, via
`src/portal/live_prefill.py`. The heuristic checker in this section still
exists and is still real (not deleted), but its role narrowed to one thing:
fast, free, deterministic AI-suggestion data for `portal/seed.py`'s demo
seeding, where running the full N-agent pipeline against 8 seeded portals x
157 questions on every reseed would be neither fast nor free. It is no
longer what the admin's pre-fill button calls. `PrefillResult` remains the
shared contract either path can be understood through.

## 3. What is being built

### 3.1 Data model additions (`shared/state/entities.py`, `shared/persistence/`)
- `AssessorRole` (A/B) and `HumanAssessorSubmission` — one append-only row per
  human answer, scoped to a role, so Assessor A's submissions are never queried
  when rendering Assessor B's screen (blindness is a query-shape guarantee, not
  a UI toggle).
- `MSQDocument` — parsed MSQ (section → Q/A pairs, extracted URLs) attached to
  a country, surfaced as read-only context in the assessor UI.
- `PublicationRecord` — append-only "this cycle+portal was published with this
  score at this time" marker; the public site only ever reads the latest one.
- `SurveyCycle.project_type` (`national_osi` | `losi_city`) and
  `TargetPortal.unit_type`/`display_name` so one schema serves both national
  surveys and city-level LOSI projects, per FR in the transcript (Section 4).

### 3.2 Admin surface (`src/portal/admin.py`)
Create a project (cycle), add indicators (questions), add units (country/city
+ portal URL), trigger an AI assessment run for a unit, upload an MSQ PDF for
a country. "Trigger an AI assessment run" now means the real 001 pipeline
(§2) dispatched as a background job (`src/portal/live_prefill.py`) with a
live status view on the project page, not a synchronous heuristic scan.

### 3.3 Assessor Portal (`src/portal/assessor.py`)
Pick a role (A or B) and a unit. See AI-suggested answers with their evidence
as a starting point (Deniz's "pre-population accelerator"), submit an
independent answer + evidence URL per question. A's submissions are never
shown while filling in B's screen, and vice versa — this is the blind
methodology from Section 2 of the transcript, applied to the real actors
(humans), not AI agent indices.

### 3.4 Discrepancy engine (`src/portal/discrepancy.py`)
After each submission, once both roles have answered at least one common
question for a unit, recompute the differing-answer rate between A and B. Over
5% (`portal_differing_answer_rate_threshold`, already configurable in
`Settings`) creates a `DiscrepancyCase` + `EscalationQueueItem`
(`PORTAL_DISCREPANCY`), reusing 001's existing escalation queue and
disposition-recording code untouched.

### 3.5 MSQ ingestion (`src/portal/msq.py`)
`pypdf` text extraction, split on the MSQ's own section markers (`A.`, `B.`,
`C.`, …) and numbered question markers (Microsoft Forms export format,
confirmed against the real sample `understanding docs/Denmark - MS MSQ
2024.pdf`), regex-extract every URL mentioned. Not a full NLP parse — a
structural split good enough to hand an assessor "here is what the government
told us for this section" without them opening the PDF.

### 3.6 Senior Reviewer publish (`src/portal/admin.py`)
One button on a resolved unit: compute an OSI-style score (fraction of
affirmative delivered answers) and write a `PublicationRecord`. This is the
"push approved data up... feeds directly into public reporting views without
manual exports/imports" requirement — no export/import step, the public site
reads the same database.

### 3.7 Public Knowledge Base (`src/portal/public.py`)
Read-only pages sourced *only* from `PublicationRecord` rows: cycle list →
ranked table of published units → unit profile page with the delivered
answer/evidence for every published indicator. Serves both a national-survey
ranking table and a LOSI city table from the same code path
(`project_type` drives the label, not the query).

## 4. Explicitly out of scope for this 2-hour window

- Drupal or any UN-hosting-specific integration (explicit instruction).
- Real authentication/authorization — role selection is a form field, not a
  login system. Noted as the first thing a production build must add.
- Full NLP parsing of MSQ content (semantic Q&A matching to indicators) —
  structural section/URL extraction only.
- TII/HCI sub-indices (external ITU/UNESCO data feeds) — OSI only, matching
  001's existing scope and Deniz's own framing that OSI is the part UN DESA
  produces directly.
- Automated screenshot capture in the heuristic pre-fill path (001's
  Playwright capture pipeline is reused as-is for the LLM-agent path; the
  heuristic path stores response snippets + the fetched URL as evidence
  instead, since there's no browser render step in a pure HTTP check).

## 5. Reused unchanged

`shared/persistence/schema.py` (extended, not replaced), `Repository` pattern,
`review/escalations.py`, `review/actions.py`, `review/api.py`,
`review/web/app.py` (mounted, not modified), the CLI's `click` structure, and
every entity from 001. The append-only discipline (FR-062 in 001) applies to
every new table added here.
