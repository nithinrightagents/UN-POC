# Environment configuration reference

This document explains every active parameter in the repository's `.env` file as inspected on 13 August 2026. Values shown below are the configured values, except credentials and personally identifying contact details, which are intentionally redacted.

Configuration is loaded at process start. A process environment variable takes precedence over `.env`, which takes precedence over the application's built-in default. Restart the process after changing a value.

## Model provider

| Parameter | Configured value | Meaning |
| --- | --- | --- |
| `GOOGLE_GENAI_USE_VERTEXAI` | `TRUE` | Routes Google GenAI/ADK calls through Vertex AI. |
| `GOOGLE_CLOUD_PROJECT` | *(empty)* | GCP project identifier. It must be supplied before a real Vertex AI run; the empty value means no project is configured in this file. |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | Vertex AI region in which portal content is processed. This is a compliance/data-residency setting as well as a service location. |
| `AIQ_AGENT_1_MODEL` | `gemini-3.5-flash` | Model used by assessor agent 1. |
| `AIQ_AGENT_2_MODEL` | `gemini-3.5-flash` | Model used by assessor agent 2. |
| `AIQ_AGENT_TEMPERATURES` | `0.1,0.1` | Comma-separated sampling temperatures, ordered by assessor-agent index. Lower values make output more deterministic. |
| `AIQ_AGENT_PROMPT_PROFILES` | `literal,inferential` | Comma-separated assessment stances: agent 1 interprets literally; agent 2 may make supported inferences. |
| `AIQ_VALIDATOR_MODEL` | `gemini-3.5-flash` | Model used by the validation stage. |
| `AIQ_ALLOW_IDENTICAL_AGENT_MODELS` | `true` | Explicitly permits both assessors to use the same model. Prompt profiles still provide a divergence axis. |

`AIQ_AGENT_MODELS` is not set. The application therefore constructs its model list from `AIQ_AGENT_1_MODEL` and `AIQ_AGENT_2_MODEL`.

## Assessment and validation

| Parameter | Configured value | Meaning |
| --- | --- | --- |
| `AIQ_ASSESSOR_AGENT_COUNT` | `2` | Number of independent assessor agents. Must be at least two. |
| `AIQ_BATCH_SIZE` | `20` | Number of items processed per batch. |
| `AIQ_ADJUDICATION_RETRY_LIMIT` | `2` | Maximum retry count when assessor outputs need adjudication. |
| `AIQ_VALIDATION_RETRY_LIMIT` | `2` | Maximum retry count for validation-stage failures or insufficient results. |
| `AIQ_VALIDATION_QUALITY_THRESHOLD` | `0.70` | Minimum validation quality score, expressed from 0 to 1. |
| `AIQ_PER_QUESTION_CONFIDENCE_THRESHOLD` | `10` | Lowest per-question confidence percentage that meets the configured question-level threshold. |

## Confidence acceptance gate

| Parameter | Configured value | Meaning |
| --- | --- | --- |
| `AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD` | `75` | Single acceptance boundary on the 0–100 confidence scale. |
| `AIQ_CONFIDENCE_RETRY_LIMIT` | `1` | Number of attempts to improve a result that does not meet the acceptance threshold. |
| `AIQ_BEST_EFFORT_CONFIDENCE_CEILING` | `74` | Highest confidence a best-effort result may receive. It must remain below the acceptance threshold. |

## Portal discrepancy and link resolution

| Parameter | Configured value | Meaning |
| --- | --- | --- |
| `AIQ_PORTAL_DIFFERING_ANSWER_RATE_THRESHOLD` | `0.10` | Flags a portal when the rate of differing assessor answers reaches the configured 10% threshold. |
| `AIQ_PORTAL_AFFIRMATIVE_RATE_GAP_THRESHOLD` | `0.10` | Flags a portal when the agents' affirmative-answer rates differ by 10 percentage points. |
| `AIQ_KB_LINK_SOURCE_ENABLED` | `true` | Allows the prior-survey knowledge base to provide candidate links. |
| `AIQ_MSQ_LINK_SOURCE_ENABLED` | `true` | Allows MSQ submissions to provide links only, never answer content. |
| `AIQ_URL_RESOLUTION_MODE` | `historical_first` | Resolves URLs in this order: historical knowledge base → MSQ submissions → web search. |

`AIQ_KB_MAX_LINK_AGE_DAYS` has been removed from the codebase (was a 730-day age bound on prior-survey KB links). The KB link source now returns a candidate regardless of how old it is, as long as one is on record.

## Language and crawling policy

| Parameter | Configured value | Meaning |
| --- | --- | --- |
| `AIQ_SUPPORTED_LANGUAGES` | `en` | Comma-separated ISO 639-1 language codes that the automated workflow supports. Currently English only. |
| `AIQ_LANGUAGE_DECISION_WINDOW_HOURS` | `48` | Time window allowed for a language-related decision or escalation. |
| `AIQ_RATE_LIMIT_PER_DOMAIN_RPS` | `0.5` | Crawl limit per domain: at most one request every two seconds on average. |
| `AIQ_UNRESPONSIVE_PORTAL_ATTEMPT_BOUND` | `3` | Maximum attempts before treating a portal as unresponsive. |
| `AIQ_VERIFICATION_ATTEMPT_BOUND` | `3` | Maximum verification attempts for a portal or response. |
| `AIQ_USER_AGENT` | `EKAP-AIQ-PoC/0.1 (+contact: [redacted])` | HTTP User-Agent sent during crawling; it identifies the proof of concept and provides a contact channel. |

## Persistence and review surface

| Parameter | Configured value | Meaning |
| --- | --- | --- |
| `AIQ_DATABASE_PATH` | `./data/aiq.db` | Relative filesystem path for the SQLite database. |
| `AIQ_SERVE_HOST` | `127.0.0.1` | Binds the review web service to the local machine only. |
| `AIQ_SERVE_PORT` | `8080` | TCP port for the local review web service. |

## LangSmith tracing

| Parameter | Configured value | Meaning |
| --- | --- | --- |
| `LANGCHAIN_TRACING_V2` | `false` | Disables LangSmith distributed tracing. Tracing runs only when this is `true` and a valid API key is present. |
| `LANGSMITH_API_KEY` | *(configured; redacted)* | Credential LangSmith uses to authenticate and submit traces. Keep this private; it must not be committed, logged, or copied into documentation. |
| `LANGSMITH_PROJECT` | `UN EGDI QSQ` | LangSmith project/workspace that receives traces when tracing is enabled. |
| `LANGCHAIN_ENDPOINT` | *(commented out)* | Optional custom LangSmith endpoint for self-hosted deployments. Without it, the standard LangSmith endpoint is used. |

## Operational notes

- Authentication for Google Cloud is expected through Application Default Credentials rather than a credential stored in `.env`.
- The startup configuration validator requires a non-empty Google Cloud project and location for Vertex use, at least two assessor agents, valid threshold ranges, and a best-effort confidence ceiling lower than the acceptance threshold.
- `.env` contains a live LangSmith credential. Rotate it if this file has been shared or committed, then move the replacement to a secret manager or injected environment variable.
