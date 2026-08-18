# Contract: Access Control, Runtime Wiring, and Limits

Covers FR-API-004 (lifecycle wiring), FR-API-014a (concurrency cap), and FR-API-035–039 (access control).

---

## 1. API key

**Header**: `X-API-Key: <secret>` on every `/api/v1/**` request. Enforced by one FastAPI dependency applied at router level, so a new endpoint cannot be added unprotected by omission.

| Condition | Response |
|---|---|
| `settings.api_key` empty | **503** `not_configured` — programmatic access is not enabled on this deployment (FR-API-039) |
| header absent, or value ≠ `settings.api_key` | **401** `unauthorized` (FR-API-036) |
| value matches | request proceeds |

Comparison uses `hmac.compare_digest` — constant-time, so a wrong key cannot be recovered by timing.

**Guarantees**:
- A refused request has **no side effects**: the dependency runs before any handler, so no job row is inserted, no task is created, and no model call is made (FR-API-037, SC-008). This is why the capacity check and job insert live in the handler's service call rather than in a dependency.
- Refusal bodies carry only the error envelope — no cycle, unit, question, answer, or score data (FR-API-036).
- Nothing about the **portal** changes: `/`, `/admin`, `/assessor`, `/public`, `/review` keep their current access behavior (FR-API-038). A deployment that never sets `AIQ_API_KEY` is a supported portal-only deployment, not a misconfiguration — the service starts normally and only `/api/v1/**` refuses.

**Secret handling**: `Settings.as_dict()` masks `api_key` as `"***"`. Required because `as_dict()` is persisted into `configuration_snapshots` (`cli.py:287`) and printed by `aiq config show`, and `verify_no_credentials` does not scan that table — see [research.md](../research.md) R6.

---

## 2. Runtime wiring (FR-API-004)

### `AIRuntime`

```
AIRuntime:
    provider:    ModelProvider          # settings.google_cloud_project / _location / _use_vertexai
    limiter:     RateLimiter            # settings.rate_limit_per_domain_rps — ONE instance, shared
    browser:     BrowserSession         # settings.user_agent + the shared limiter
    http_client: httpx.AsyncClient      # timeout=15.0, matching cli.py and live_prefill.py

    async def start() -> None   # browser.start() — launches Chromium once
    async def stop()  -> None   # browser.stop(), http_client.aclose()
```

### Lifespan, on `portal/webapp.py`'s app

```
startup:
    init_db(database_path)                  # idempotent; creates assessment_jobs if absent
    sweep_interrupted_jobs(conn)            # BEFORE serving — see assessment-job.md
    runtime = AIRuntime(settings); await runtime.start()
    app.state.ai_runtime = runtime
shutdown:
    await runtime.stop()
```

The lifespan lives on the **parent** app, not on a mounted sub-application: Starlette does not run a mounted app's lifespan, so a mounted API's runtime would silently never start and the first fetch would trip `BrowserSession`'s `assert self._browser is not None` ([research.md](../research.md) R1).

**Per-run, not shared** (unchanged from `live_prefill.py`): the SQLite connection, `FetchLog`, `StageEventLog`, `CostLedger`, and the capture directory — all session-scoped and created inside the background task, which is what keeps telemetry and cost records identical to a CLI run (SC-010).

**Shared deliberately**: the rate limiter. One instance across all concurrent runs is what makes the per-domain limit actually per-domain; today each run builds its own, so two runs against one government domain each get the full budget ([research.md](../research.md) R2).

---

## 3. Concurrency cap (FR-API-014a)

| Parameter | Env | Default |
|---|---|---|
| `max_concurrent_assessment_runs` | `AIQ_MAX_CONCURRENT_ASSESSMENT_RUNS` | `2` |

- Counted as `SELECT COUNT(*) FROM assessment_jobs WHERE state='running'` — **globally**, across both API and portal triggers, since both now go through one service.
- Over the cap → **429** `capacity_reached` with `Retry-After`. Nothing is queued and no `pending` state exists (FR-API-014a keeps the three observable states of FR-API-018 intact).
- An idempotent re-trigger of an already-running unit is **not** subject to the cap; it starts no run.
- `validate_settings` rejects a value below 1.

Default of 2 is deliberate: one run is already up to `batch_size` (default 50) concurrently-processed units × `assessor_agent_count` (default 2) agent calls each, so this cap bounds worst-case in-flight model calls at roughly 2 × 50 × 2 rather than "however many units a client loops over".

This is the only limit this feature introduces. Request-rate limiting, quotas, and usage metering of the interface itself remain out of scope.
