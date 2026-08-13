# Contract: Configuration

**Satisfies**: FR-072–FR-075, SC-010 | **Source**: `.env`, read at process start (spec, Implementation Constraints)

Every operational parameter is externalized. No operational constant appears as a literal in code. A change takes effect without a code edit or rebuild; a process restart is acceptable (FR-074).

## Parameters

All parameters named in FR-072.

| Env var | Type | Default | Validation | Req |
|---|---|---|---|---|
| `AIQ_ASSESSOR_AGENT_COUNT` | int | `2` | **≥ 2** — run rejected below | FR-008, FR-009 |
| `AIQ_BATCH_SIZE` | int | `50` | ≥ 1 | FR-064 |
| `AIQ_ADJUDICATION_RETRY_LIMIT` | int | `2` | ≥ 0 | FR-032 |
| `AIQ_VALIDATION_RETRY_LIMIT` | int | `2` | ≥ 0 | FR-084 |
| `AIQ_VALIDATION_QUALITY_THRESHOLD` | float | `0.70` | 0.0–1.0 | FR-078 |
| `AIQ_PER_QUESTION_CONFIDENCE_THRESHOLD` | int | `10` | 0–100 | FR-029 |
| `AIQ_PORTAL_DIFFERING_ANSWER_RATE_THRESHOLD` | float | `0.10` | 0.0–1.0 | FR-037 |
| `AIQ_PORTAL_AFFIRMATIVE_RATE_GAP_THRESHOLD` | float | `0.10` | 0.0–1.0 | FR-037 |
| `AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD` | int | `75` | 0–100. The **only** boundary drawn on the scale (FR-041) | FR-134 |
| `AIQ_CONFIDENCE_RETRY_LIMIT` | int | `1` | ≥ 0; tracked separately from validation and adjudication retries | FR-137 |
| `AIQ_BEST_EFFORT_CONFIDENCE_CEILING` | int | `74` | 0–100; must be **below** the acceptance threshold | FR-018 |
| `AIQ_KB_LINK_SOURCE_ENABLED` | bool | `true` | Prior-survey KB as a **link** source | FR-122 |
| `AIQ_MSQ_LINK_SOURCE_ENABLED` | bool | `true` | MSQ submissions read for **links** only, never for answers | FR-122, FR-126 |
| `AIQ_KB_MAX_LINK_AGE_DAYS` | int | `730` | ≥ 1; one biennial cycle | FR-128 |
| `AIQ_SUPPORTED_LANGUAGES` | csv | *(empty)* | ISO 639-1 codes | FR-014 |
| `AIQ_RATE_LIMIT_PER_DOMAIN_RPS` | float | `0.5` | > 0 | FR-069 |
| `AIQ_UNRESPONSIVE_PORTAL_ATTEMPT_BOUND` | int | `3` | ≥ 1 | FR-071 |
| `AIQ_LANGUAGE_DECISION_WINDOW_HOURS` | int | `48` | ≥ 1 | FR-019 |
| `AIQ_VERIFICATION_ATTEMPT_BOUND` | int | `3` | ≥ 1 | FR-088 |
| `AIQ_URL_RESOLUTION_MODE` | enum | `historical_first` | `msq_first` \| `historical_first` \| `search_first`. **Default is `historical_first`** — prior-survey KB, then MSQ, then search | FR-003 |

### Notes on specific defaults

- **`AIQ_SUPPORTED_LANGUAGES` defaults to empty.** Deliberate. Its contents depend on a language-coverage evaluation of the configured models (spec, Dependencies), which is a project activity and a prerequisite for a first production run. An empty set routes every portal to a human language decision (FR-017) — visibly wrong, and therefore safe. A plausible-looking default would silently assert coverage nobody has established.
- **`AIQ_BEST_EFFORT_CONFIDENCE_CEILING = 74`** sits one point below the acceptance threshold, so a translated answer never clears the threshold on its own. The two are coupled: move the threshold and this must move with it, which the startup validator below enforces.
- **Named confidence tiers no longer exist** (FR-041). Confidence is displayed as a 0–100 percentage everywhere, and the acceptance threshold is the single boundary. `AIQ_CONFIDENCE_TIER_BANDS` was removed rather than defaulted — two labels for one number let a reader trust the label and skip the number.
- **`AIQ_ASSESSOR_AGENT_COUNT` below 2 rejects the run** rather than degrading to a single agent (FR-009). Silent degradation would destroy the discrepancy signal while producing output that looks normal.

## Model provider (research R2)

Vertex AI with GCP authentication. These are operational parameters under FR-072 even though the spec does not enumerate them — the spec is deliberately provider-neutral, so the binding lives here.

| Env var | Type | Default | Notes |
|---|---|---|---|
| `GOOGLE_GENAI_USE_VERTEXAI` | bool | `TRUE` | ADK's switch to the Vertex backend |
| `GOOGLE_CLOUD_PROJECT` | string | *(required)* | No default; startup fails without it |
| `GOOGLE_CLOUD_LOCATION` | string | *(required)* | **A compliance setting, not a latency one** — determines where portal content is processed (Phase 3 §8.2) |
| `AIQ_AGENT_MODELS` | csv | `gemini-flash,gemini-flash` | One model per agent index, in order. Length must equal `AIQ_ASSESSOR_AGENT_COUNT`. **Interim: same flash model for all agents** — see below. |
| `AIQ_AGENT_TEMPERATURES` | csv | `0.2,0.7` | Per agent index. **Interim: the primary divergence axis**, not a supplement. |
| `AIQ_AGENT_PROMPT_PROFILES` | csv | `literal,inferential` | Per agent index; named evaluative stances (research R7) |
| `AIQ_VALIDATOR_MODEL` | string | `gemini-flash` | The Validator's model; may match an agent's |
| `AIQ_ALLOW_IDENTICAL_AGENT_MODELS` | bool | `false` | Must be `true` to run agents on the same model — see below |

> **Model ID needs confirming.** `gemini-flash` above is a placeholder standing in for the flash model the stakeholder named ("3.5 flash"), which does not map to a Vertex model ID I can verify. Confirm the exact string against `gcloud ai models list` or the Vertex model garden for the project, then set it once — it appears in `AIQ_AGENT_MODELS` and `AIQ_VALIDATOR_MODEL`.

### Interim posture: one model for all agents

The current decision is a **single flash model across every Assessor Agent**, to be tuned later once benchmark evidence exists. That is a reasonable starting point, and it has one consequence that must not be silent.

FR-011 states that identically configured agents producing correlated outputs **do not satisfy** independence — correlated agreement is indistinguishable from one agent run twice, and it destroys the signal adjudication depends on. With a shared model, independence rests entirely on temperature and prompt-profile divergence, which research R7 rates as the weaker axes.

So the check stays, but as an **explicit override rather than a block**:

- `AIQ_ALLOW_IDENTICAL_AGENT_MODELS=false` (default) → identical models across all agent indices **rejects the run**.
- `AIQ_ALLOW_IDENTICAL_AGENT_MODELS=true` → permitted, and the fact is **written into the Configuration Snapshot** (FR-063), so any session run this way is identifiable afterwards and any benchmark comparison across configurations (FR-098, FR-099) shows it as a difference.

The point is not to obstruct the interim choice. It is that when SC-003's flag rate comes in near its 5% non-independence floor, the configuration snapshot should already answer *why* — rather than leaving it to be rediscovered.

**This configuration is the one most likely to trip that floor.** Under SC-003 a low flag rate is a **failure**, not a success. Treat the first benchmark run as a test of the interim configuration itself, not only of the pipeline.

### Credentials are deliberately absent from this table

Authentication is **Application Default Credentials**, or a service account in non-interactive environments. No key material appears in `.env`.

This is not stylistic. The Configuration Snapshot (FR-063) captures the effective parameter set, is retained for audit, and is read back by anyone reconstructing a session under FR-061 — so anything in `.env` is effectively published to every future auditor of that session. Credentials must not be in that set. It also keeps FR-117 (no credentials in telemetry) true by construction rather than by filtering.

### Additional startup validation

- `len(AIQ_AGENT_MODELS) == AIQ_ASSESSOR_AGENT_COUNT` — a mismatch means some agent has no model or a model is silently unused. Same for `AIQ_AGENT_TEMPERATURES` and `AIQ_AGENT_PROMPT_PROFILES` when set.
- **All entries in `AIQ_AGENT_MODELS` identical → reject unless `AIQ_ALLOW_IDENTICAL_AGENT_MODELS=true`** (see above).
- **Agents identical on *every* axis → reject unconditionally.** Same model, same temperature, and same prompt profile leaves no divergence at all; the override does not extend this far, because at that point the N agents are one agent run N times and FR-011 has no remaining foothold.
- `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` present and non-empty.

### Resolution modes (FR-003)

Exactly three named orderings of the three source types:

| Mode | Order |
|---|---|
| `msq_first` | MSQ submissions → historical DB → search discovery |
| `historical_first` | historical DB → MSQ submissions → search discovery |
| `search_first` | search discovery → MSQ submissions → historical DB |

A later source is consulted only when every earlier one yielded no usable URL (FR-002).

## Inspection interface (FR-073)

The system exposes every parameter with its **current effective value** and its **default**, so an operator can see how a session was configured without inspecting internals:

```
$ aiq config show
PARAMETER                                  EFFECTIVE      DEFAULT        SOURCE
AIQ_ASSESSOR_AGENT_COUNT                   3              2              .env
AIQ_VALIDATION_QUALITY_THRESHOLD           0.70           0.70           default
AIQ_SUPPORTED_LANGUAGES                    en,fr,es       (empty)        .env
...
```

## Snapshot semantics (FR-075)

At session start the full effective set is captured into a Configuration Snapshot bound to the session.

- **Retries read the snapshot, never live configuration.** A retry is therefore comparable to the run that triggered it.
- A mid-session `.env` change takes effect only for **subsequent** sessions, and both the snapshot and the change are recorded.
- Any past session's effective configuration is retrievable from its snapshot (SC-010), which is what makes benchmark runs comparable across configuration changes (FR-098, FR-099).

## Validation at startup

The run is rejected — not warned — when:

1. `AIQ_ASSESSOR_AGENT_COUNT < 2` (FR-009).
2. `AIQ_BEST_EFFORT_CONFIDENCE_CEILING` is at or above `AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD` — a translated answer could then clear the threshold on its own, defeating FR-018.
3. Any threshold falls outside its stated range.
4. `AIQ_URL_RESOLUTION_MODE` is not one of the three named modes.
5. Both `AIQ_KB_LINK_SOURCE_ENABLED` and `AIQ_MSQ_LINK_SOURCE_ENABLED` are false *and* live search is unavailable — no link could then be resolved (FR-121, FR-122).

Rejection is at startup rather than first use so a misconfiguration cannot consume any of the shared per-domain budget before surfacing.
