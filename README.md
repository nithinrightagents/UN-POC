# UN EKAP — Assessment & Workflow Engine

AI-assisted e-government assessment platform for UN DESA (United Nations Department of Economic and Social Affairs).

## UN EKAP Assessment & Workflow Platform

UN EKAP provides the complete multi-tenant assessment workflow:
- **Admin & Survey Governance**: Spin up biennial survey cycles (National OSI for 193 Member States, LOSI for Municipalities), manage indicator sets, and trigger AI pre-fill.
- **Blind Assessor A/B Intake**: Independent evaluation by two blind human assessors with AI suggestions serving as a human-in-the-loop starting accelerator.
- **Automated Discrepancy Arbitration**: Automatic detection when Assessor A and B answers disagree beyond the configurable threshold (>5%), routing disputes to the Senior Reviewer arbitration queue.
- **Member State Questionnaire (MSQ) Ingestion**: Direct extraction and ingestion of 50+ page government MSQ submissions (Modules 2.1–2.6) for evidence contextualization.
- **Public Knowledge Base**: One-click publication workflow displaying member state rankings, scores, and open data profiles.

```bash
aiq db init
aiq seed demo        # two real projects, live government portals, real MSQ ingestion
aiq serve            # launch Admin, Assessor Portal, Public KB, AI Review & /api/v1 REST API
```

## Programmatic REST API

The platform exposes a headless JSON REST API under `/api/v1` (spec `007-headless-rest-api`):
- **Cycles, Questions & Units**: `POST/GET /api/v1/cycles`, `POST/GET /api/v1/cycles/{id}/questions`, `POST/GET /api/v1/cycles/{id}/units`
- **Assessment Runs**: `POST /api/v1/cycles/{id}/units/{portal_id}/assessment` (trigger), `GET .../assessment` (poll status), `GET .../results` (AI results)
- **Human Assessor Answers**: `POST/GET /api/v1/cycles/{id}/units/{portal_id}/human-answers?role={A|B}` (role-scoped blind submissions)
- **Publication**: `POST/GET /api/v1/cycles/{id}/units/{portal_id}/publication`

### Configuration

Set via environment or `.env`:
- `AIQ_API_KEY`: Secret string required in `X-API-Key` header for `/api/v1/**` requests. If unset, API requests return `503 not_configured` while portal UI continues operating normally.
- `AIQ_MAX_CONCURRENT_ASSESSMENT_RUNS`: Maximum concurrent AI assessment runs (default: `2`, must be $\ge 1$).

## Decoupled AI Prefill (Spec 008)

The AI assessment pipeline functions as a decoupled prefill generator:
- **Assessor Starts From Prefill**: Human assessors have 100% authority to accept, edit, or override suggestions with human-only publication precedence.
- **Headless Execution & Reasons**: Headless prefill generation with unambiguous `PrefillReason` taxonomies (`no_usable_evidence`, `unresolved_disagreement`, `failed_final_validation`, `budget_reached`, etc.).
- **Impartial Resolver Agent**: Resolves disputes between two independent assessor agents when answers or confidences differ beyond threshold (`resolved_dispute`).
- **Final Validation Gate**: Single-pass element verification guarding delivered suggestions before persisting.
- **Run Budget & Resumability**: Configurable `AIQ_PREFILL_RUN_BUDGET` per-unit spend limit. Safe repeated re-runs preserve 100% of human submissions.

## What this does

For each question–portal pair: resolve a link (prior-survey KB → MSQ → internet search), traverse
it live, assess it with N = 2 independent AI assessor agents, arbitrate agreements or resolve disputes via the Resolver Agent, validate through the Final Validation Gate, persist the prefill record, and present the suggestion to human assessors as a high-confidence accelerator.

## Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -e ".[dev]"
playwright install chromium

cp .env.example .env
# edit .env: set GOOGLE_CLOUD_PROJECT, AIQ_API_KEY, and confirm AIQ_AGENT_MODELS

gcloud auth application-default login
gcloud config set project "$GOOGLE_CLOUD_PROJECT"
```

No credentials are ever written to `.env` — authentication is Application Default Credentials
(ADC), kept out of the audited configuration snapshot. See
[contracts/configuration.md](specs/001-ekap-aiq-assessment/contracts/configuration.md).

## Commands

```bash
aiq config show                      # every parameter, effective value, default, source
aiq db init                          # create the append-only schema

aiq seed demo-review                 # seed data for the review surface, no pipeline needed

aiq run --cycle <name>               # run a batch
aiq resume --cycle <name>            # resume an interrupted batch

aiq question add --cycle <name> --text "..." --type binary   # custom question (FR-053)

aiq benchmark run --set <name>       # benchmark mode against a labelled set
aiq benchmark compare --run a --run b

aiq export --cycle <name> --out ./out/

aiq telemetry summary --session <id>
aiq telemetry timings --session <id>
aiq telemetry fetches --session <id>
aiq telemetry cost --session <id>

aiq verify independence --session <id>
aiq verify evidence --session <id>
aiq verify resume --session <id>
aiq verify no-credentials
aiq verify telemetry-hygiene --session <id>
aiq verify benchmark-isolation --session <id>
```

Full walkthrough: [quickstart.md](specs/001-ekap-aiq-assessment/quickstart.md).

## Tests

```bash
pytest                          # everything
pytest -m independence          # the assertions that make the method defensible
pytest -m unit                  # domain logic — no browser, model, or network
```

## Project layout

- `src/api/` — Headless JSON REST API routers, background job runner, error envelope, security dependencies
- `src/portal/` — UN EKAP Web UI (Admin, Assessor, Public Knowledge Base, Shared Webapp)
- `src/review/` — Human review and adjudication verification surface
- `src/agents/` — Assessor, Validator, Adjudicator, Heuristic Pre-fill agents
- `src/orchestration/` — Pipeline execution, scheduler, rate-limiting
- `src/shared/` — Persistence, database schema, domain entities, configuration settings

