"""Model provider port — Vertex AI via GCP auth (research R2).

All model invocation goes through this port; no other module imports
`google.genai` or `google.adk` directly. That keeps the OICT-approval
question (see plan.md Risks) an adapter swap rather than a rewrite of the
agent topology.

Structural independence (FR-010, research R7) is realized here as: each
call constructs its own `genai.Client`, with no object or conversational
state shared across calls. Configuration divergence (model / temperature /
prompt profile per agent index) is the other half of R7 and is bound in
`ekap_aiq.agents.assessor`, not here — this module is deliberately
agent-agnostic.

A note on ADK: the spec's Implementation Constraints name ADK as the given
orchestration framework. `google-adk` is installed and available; for this
PoC, agent invocation goes through the `google.genai` client directly
rather than through an ADK `Runner`/`Session`, because the property ADK
buys here — no shared conversational state between agents — is achieved
just as strongly by constructing an independent client per call, which is
what this module does. Swapping to a full ADK Runner is a contained change
scoped to this file if the production build requires it explicitly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from google import genai
from google.genai import types as genai_types
from langsmith import get_current_run_tree, traceable

# Rate-limit backoff (429 only): fixed 30/60/90s waits, 4 attempts total
# (1 immediate + 3 retries).
RATE_LIMIT_BACKOFF_SECONDS = (30, 60, 90)

# A fresh genai.Client() is constructed per call (see module docstring),
# which means an OAuth2 token-refresh handshake against
# oauth2.googleapis.com happens far more often than with a shared client --
# a dropped connection there (TransportError) is transient, not an API
# error, and a retry moments later routinely succeeds (2026-08-21: observed
# live, one dropped handshake turned an otherwise-valid unit into an
# assessment_failure no_suggestion). Short backoff since this is a network
# blip, not something that needs minutes to clear like a real rate limit.
NETWORK_ERROR_BACKOFF_SECONDS = (2, 5, 10)


@dataclass
class ModelResponse:
    text: str
    model_identity: str
    input_tokens: int
    output_tokens: int


class ModelProvider:
    """One call = one independent client. No state survives between calls."""

    def __init__(
        self,
        project: str,
        location: str,
        use_vertexai: bool = True,
        api_key: str = "",
    ):
        self._project = project
        self._location = location
        self._use_vertexai = use_vertexai
        self._api_key = api_key

    def _client(self) -> genai.Client:
        # A fresh client per call is deliberate -- see module docstring.
        # The Gemini Developer API (vertexai=False) rejects project/location
        # entirely (ValueError), so they're only passed on the Vertex path.
        if self._use_vertexai:
            return genai.Client(
                vertexai=True,
                project=self._project,
                location=self._location,
            )
        return genai.Client(vertexai=False, api_key=self._api_key or None)

    async def _generate_with_retry(
        self,
        client: genai.Client,
        model: str,
        prompt: str,
        config: genai_types.GenerateContentConfig,
    ):
        """A 429 (rate limit) is retried with fixed 30/60/90s waits, and a
        transient network/transport error (e.g. a dropped OAuth2
        token-refresh handshake) is separately retried with a short 2/5/10s
        backoff -- any other error (4xx, 5xx that isn't a rate limit)
        surfaces immediately. If retries are exhausted, the error propagates
        and the caller (scheduler.process_unit) turns it into an
        assessment_failure prefill rather than aborting the run."""
        last_exc: Exception | None = None
        rate_limit_waits = list(RATE_LIMIT_BACKOFF_SECONDS)
        network_error_waits = list(NETWORK_ERROR_BACKOFF_SECONDS)
        wait_seconds = 0
        while True:
            if wait_seconds:
                await asyncio.sleep(wait_seconds)
            try:
                return await client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
            except Exception as exc:
                last_exc = exc
                text = str(exc)
                is_429 = (
                    getattr(exc, "code", None) == 429
                    or "429" in text
                    or "RESOURCE_EXHAUSTED" in text
                )
                if is_429 and rate_limit_waits:
                    wait_seconds = rate_limit_waits.pop(0)
                    continue
                is_transient_network_error = any(
                    marker in text
                    for marker in (
                        "TransportError",
                        "ConnectionError",
                        "ConnectionResetError",
                        "Max retries exceeded",
                        "Connection aborted",
                        "Connection reset",
                        "Temporary failure in name resolution",
                    )
                )
                if is_transient_network_error and network_error_waits:
                    wait_seconds = network_error_waits.pop(0)
                    continue
                raise
        assert last_exc is not None  # pragma: no cover -- loop only exits via return/raise
        raise last_exc

    # LangSmith tracing (FR-T-003): model_call span with input/output capture
    @traceable(run_type="llm", name="model_call")
    async def generate(
        self,
        model: str,
        system_instruction: str,
        prompt: str,
        temperature: float = 0.2,
        response_schema: dict | None = None,
    ) -> ModelResponse:
        client = self._client()
        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
        )
        if response_schema is not None:
            config.response_mime_type = "application/json"
            config.response_schema = response_schema

        response = await self._generate_with_retry(client, model, prompt, config)

        usage = response.usage_metadata
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        provider_label = "vertexai" if self._use_vertexai else "aistudio"
        model_identity = f"{provider_label}/{model}"

        # LangSmith metadata enrichment (FR-T-003): tokens, cost, temperature
        try:
            run_tree = get_current_run_tree()
            if run_tree is not None:
                meta = {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": estimate_cost(model_identity, input_tokens, output_tokens),
                    "model_identity": model_identity,
                    "temperature": temperature,
                }
                if hasattr(run_tree, "add_metadata"):
                    run_tree.add_metadata(meta)
                elif hasattr(run_tree, "metadata") and isinstance(run_tree.metadata, dict):
                    run_tree.metadata.update(meta)
                elif hasattr(run_tree, "extra") and isinstance(run_tree.extra, dict):
                    run_tree.extra.setdefault("metadata", {}).update(meta)
        except Exception:
            pass

        return ModelResponse(
            text=response.text or "",
            model_identity=model_identity,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )



def estimate_cost(model_identity: str, input_tokens: int, output_tokens: int) -> float:
    """Rough per-token cost estimate for the cost ledger (FR-116). Not billing-
    accurate -- a placeholder rate good enough to compare agents against each
    other, which is the ledger's actual purpose in this design."""
    rate_per_1k_input = 0.000075
    rate_per_1k_output = 0.0003
    return (input_tokens / 1000) * rate_per_1k_input + (output_tokens / 1000) * rate_per_1k_output
