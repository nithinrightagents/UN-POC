"""Question-set registry for guided project creation (spec 005 admin UI).

Discovers the indicator-set JSON files that ship under data/questionnaires/
and exposes them as selectable options, replacing the free-text
questionnaire_ref field that previously loaded no actual questions. Also
the single loader both the admin "create project" flow and portal/seed.py's
demo-data seeding use, so the two never drift.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

from shared.state.entities import AnswerType, EvidenceLocus, Question

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_SET_DIRS = [
    _REPO_ROOT / "data" / "questionnaires" / "templates",
    _REPO_ROOT / "data" / "questionnaires" / "modules",
]


@dataclass(frozen=True)
class QuestionSetInfo:
    set_id: str
    label: str
    question_count: int
    path: pathlib.Path


def list_question_sets() -> list[QuestionSetInfo]:
    """Templates and modules use different metadata keys (template_id/name
    vs module_id/module) -- normalized here so callers don't need to know
    which shape a given file is."""
    sets: list[QuestionSetInfo] = []
    for set_dir in _SET_DIRS:
        if not set_dir.exists():
            continue
        for path in sorted(set_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            questions = data.get("questions", [])
            label = data.get("name") or data.get("module") or path.stem
            sets.append(
                QuestionSetInfo(
                    set_id=path.stem,
                    label=label,
                    question_count=data.get("total_questions", len(questions)),
                    path=path,
                )
            )
    return sets


def load_question_set(set_id: str, cycle_id: str) -> list[Question]:
    """question_id is a global primary key (schema.py), so a cycle-local
    prefix keeps two projects using the same indicator set from colliding.
    indicator_id stays the bare PF-### -- that's what the heuristic
    checker's PrefillResult keys on (agents/prefill/heuristic.py).

    `set_id` is looked up only against the registry built by
    list_question_sets() -- never joined directly onto a filesystem path --
    since it can arrive from an admin-submitted form field."""
    known = {s.set_id: s for s in list_question_sets()}
    info = known.get(set_id)
    if info is None:
        raise ValueError(f"Unknown question set '{set_id}'")

    data = json.loads(info.path.read_text(encoding="utf-8"))
    return [
        Question(
            question_id=f"{cycle_id}:{q['question_id']}",
            cycle_id=cycle_id,
            text=q["text"],
            answer_type=AnswerType(q["answer_type"]),
            evidence_locus=EvidenceLocus(q["evidence_locus"]),
            indicator_id=q.get("indicator_id"),
            question_class=q.get("module") or q.get("question_class"),
            title=q.get("title"),
            what=q.get("what"),
            why=q.get("why"),
            how=q.get("how"),
            benchmark_case=q.get("benchmark_case"),
            reference_links=q.get("reference_links", []),
        )
        for q in data["questions"]
    ]
