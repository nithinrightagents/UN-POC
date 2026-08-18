"""Resolver prompts and system instructions (spec 008 FR-PF-026)."""

RESOLVER_SYSTEM_INSTRUCTION = """You are an expert impartial adjudicator reviewing two independent AI assessor evaluations of a government portal indicator question.
Your task is to analyze the discrepancy between Position A and Position B, evaluate the cited justifications and evidence, and decide which position is better supported by facts, or declare the outcome undetermined if the evidence is insufficient or equally unconvincing.

Rules:
1. You may only select Position A or Position B. You cannot invent a third answer.
2. If neither position provides compelling evidence or if evidence is ambiguous/contradictory, return selected_run_id as null and undetermined as true.
3. You must characterize the nature of the disagreement and provide clear reasoning for your decision.
4. Output valid JSON matching the schema."""

_RESOLVER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "disagreement_characterization": {
            "type": "string",
            "description": "Succinct summary of what the two positions dispute (e.g. interpretation of scope vs feature absence).",
        },
        "selected_run_id": {
            "type": ["string", "null"],
            "description": "The run_id of the better-supported position, or null if undetermined.",
        },
        "reasoning": {
            "type": "string",
            "description": "Detailed reasoning explaining why the selected position is superior or why the case is undetermined.",
        },
        "confidence": {
            "type": ["integer", "null"],
            "description": "Confidence score (0-100) in the resolved position, or null if undetermined.",
        },
        "undetermined": {
            "type": "boolean",
            "description": "True if neither position is chosen, False if a position is selected.",
        },
    },
    "required": ["disagreement_characterization", "reasoning", "undetermined"],
}


def build_resolver_prompt(
    question_text: str,
    portal_url: str,
    position_a: dict,
    position_b: dict,
    disagreement_points: list[str],
) -> str:
    points_str = "\n".join(f"- {p}" for p in disagreement_points)
    return f"""Indicator Question: {question_text}
Portal URL: {portal_url}

Points of Disagreement:
{points_str}

Position A:
- Run ID: {position_a.get('run_id')}
- Answer: {position_a.get('answer')}
- Stated Confidence: {position_a.get('confidence')}
- Justification: {position_a.get('justification')}
- Evidence Text: {position_a.get('evidence_text') or 'None'}
- Evidence URL: {position_a.get('evidence_url') or 'None'}

Position B:
- Run ID: {position_b.get('run_id')}
- Answer: {position_b.get('answer')}
- Stated Confidence: {position_b.get('confidence')}
- Justification: {position_b.get('justification')}
- Evidence Text: {position_b.get('evidence_text') or 'None'}
- Evidence URL: {position_b.get('evidence_url') or 'None'}

Evaluate both positions and decide:
1. What is the fundamental nature of the disagreement?
2. Which position (if either) is definitively supported by the cited evidence?
3. Select the winning run_id, or declare undetermined=true if both are weak/unconvincing."""
