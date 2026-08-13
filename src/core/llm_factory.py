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

from dataclasses import dataclass

from google import genai
from google.genai import types as genai_types
from langsmith import get_current_run_tree, traceable


@dataclass
class ModelResponse:
    text: str
    model_identity: str
    input_tokens: int
    output_tokens: int


class ModelProvider:
    """One call = one independent client. No state survives between calls."""

    def __init__(self, project: str, location: str, use_vertexai: bool = True):
        self._project = project
        self._location = location
        self._use_vertexai = use_vertexai

    def _client(self) -> genai.Client:
        # A fresh client per call is deliberate -- see module docstring.
        return genai.Client(
            vertexai=self._use_vertexai,
            project=self._project,
            location=self._location,
        )

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

        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )

        usage = response.usage_metadata
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        model_identity = f"vertexai/{model}"

        # LangSmith metadata enrichment (FR-T-003): tokens, cost, temperature
        try:
            run_tree = get_current_run_tree()
            if run_tree is not None:
                run_tree.patch(metadata={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": estimate_cost(model_identity, input_tokens, output_tokens),
                    "model_identity": model_identity,
                    "temperature": temperature,
                })
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
