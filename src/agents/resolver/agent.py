"""Resolver Agent implementation (spec 008 FR-PF-026)."""

from __future__ import annotations

import json
import re
from typing import Any

from agents.resolver.prompts import (
    RESOLVER_SYSTEM_INSTRUCTION,
    _RESOLVER_JSON_SCHEMA,
    build_resolver_prompt,
)
from agents.resolver.schema import ResolverDecision
from core.llm_factory import ModelProvider, estimate_cost
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.stage_events import StageEventLog
from shared.config.settings import Settings
from shared.state.entities import AssessorAgentRun


class ResolverAgent:
    """Impartial adjudicator that resolves disputes between two assessor positions."""

    def __init__(self, provider: ModelProvider | None = None):
        self.provider = provider

    async def resolve(
        self,
        *,
        question_text: str,
        portal_url: str,
        runs: list[AssessorAgentRun],
        disagreement_points: list[str],
        settings: Settings,
        provider: ModelProvider | None = None,
        stage_log: StageEventLog | None = None,
        cost_ledger: CostLedger | None = None,
    ) -> ResolverDecision:
        if len(runs) < 2:
            return ResolverDecision(
                disagreement_characterization="Insufficient positions to resolve",
                selected_run_id=None,
                reasoning="Fewer than 2 positions provided to resolver.",
                confidence=None,
                undetermined=True,
            )

        active_provider = provider or self.provider
        if not active_provider:
            return ResolverDecision(
                disagreement_characterization="No model provider configured",
                selected_run_id=None,
                reasoning="Model provider unavailable.",
                confidence=None,
                undetermined=True,
            )

        valid_run_ids = {runs[0].run_id, runs[1].run_id}
        pos_a = {
            "run_id": runs[0].run_id,
            "answer": runs[0].answer,
            "confidence": runs[0].confidence,
            "justification": runs[0].justification,
            "evidence_text": getattr(runs[0], "evidence_quote", None)
            or getattr(runs[0], "_pending_evidence", None),
            "evidence_url": getattr(runs[0], "evidence_url", None) or portal_url,
        }
        pos_b = {
            "run_id": runs[1].run_id,
            "answer": runs[1].answer,
            "confidence": runs[1].confidence,
            "justification": runs[1].justification,
            "evidence_text": getattr(runs[1], "evidence_quote", None)
            or getattr(runs[1], "_pending_evidence", None),
            "evidence_url": getattr(runs[1], "evidence_url", None) or portal_url,
        }

        prompt = build_resolver_prompt(
            question_text=question_text,
            portal_url=portal_url,
            position_a=pos_a,
            position_b=pos_b,
            disagreement_points=disagreement_points,
        )

        model = getattr(
            settings,
            "resolver_model",
            getattr(settings, "validator_model", "gemini-2.5-flash"),
        )

        try:
            response = await active_provider.generate(
                model=model,
                system_instruction=RESOLVER_SYSTEM_INSTRUCTION,
                prompt=prompt,
                temperature=0.0,
                response_schema=_RESOLVER_JSON_SCHEMA,
            )
            if cost_ledger:
                cost_ledger.record(
                    stage="resolution",
                    model_identity=response.model_identity,
                    input_units=response.input_tokens,
                    output_units=response.output_tokens,
                    cost=estimate_cost(
                        response.model_identity,
                        response.input_tokens,
                        response.output_tokens,
                    ),
                    agent_index=None,
                )

            data = _parse_model_json(response.text)
            char = str(
                data.get("disagreement_characterization")
                or "Dispute over indicator evidence"
            ).strip()
            reasoning = str(data.get("reasoning") or "Evaluated positions.").strip()
            selected_id = data.get("selected_run_id")
            undetermined = bool(data.get("undetermined", False))

            # Coercion to undetermined (FR-PF-026d)
            if selected_id not in valid_run_ids or undetermined or selected_id is None:
                return ResolverDecision(
                    disagreement_characterization=char
                    or "Unresolved disagreement between assessor positions",
                    selected_run_id=None,
                    reasoning=reasoning
                    or "Resolver could not definitively favor either position.",
                    confidence=None,
                    undetermined=True,
                )

            conf_val = data.get("confidence")
            conf = int(conf_val) if conf_val is not None else None
            return ResolverDecision(
                disagreement_characterization=char,
                selected_run_id=selected_id,
                reasoning=reasoning,
                confidence=conf,
                undetermined=False,
            )
        except Exception as exc:
            return ResolverDecision(
                disagreement_characterization=f"Resolver error: {type(exc).__name__}",
                selected_run_id=None,
                reasoning=f"Resolution failed due to exception: {str(exc)}",
                confidence=None,
                undetermined=True,
            )


def _parse_model_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}
