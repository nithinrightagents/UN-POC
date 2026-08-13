# EKAP AIQ — Proof of Concept

AI-assisted pre-fill of the UN e-government assessment questionnaire (Module 2.1 — Institutional
Framework) for a fixed set of countries. See [specs/001-ekap-aiq-assessment/spec.md](specs/001-ekap-aiq-assessment/spec.md)
for the full specification and [plan.md](specs/001-ekap-aiq-assessment/plan.md) for the design.

## What this does

For each question–portal pair: resolve a link (prior-survey KB → MSQ → internet search), traverse
it live, assess it with N ≥ 2 independent AI agents, validate each agent's output against the live
page, adjudicate the validated positions into a consensus answer, and present the complete
pre-filled set to a human for approval, edit, or override.

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
# edit .env: set GOOGLE_CLOUD_PROJECT and confirm AIQ_AGENT_MODELS

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
aiq serve                            # start the review web app

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

See [plan.md](specs/001-ekap-aiq-assessment/plan.md) §Project Structure.
