"""Validator Agent Pydantic output schemas."""

from __future__ import annotations

from pydantic import BaseModel


class JudgmentOutput(BaseModel):
    evidence_supports_answer: bool
    justification_consistent: bool
    confidence_proportionate: bool
    gaps: list[str]


__all__ = ["JudgmentOutput"]
