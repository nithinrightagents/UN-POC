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

from shared.state.entities import AnswerType, EvidenceLocus, Question, SurveyCycle

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_CUSTOM_DIR = _REPO_ROOT / "data" / "questionnaires" / "custom"
_SET_DIRS = [
    _REPO_ROOT / "data" / "questionnaires" / "templates",
    _REPO_ROOT / "data" / "questionnaires" / "modules",
    _CUSTOM_DIR,
]


@dataclass(frozen=True)
class QuestionSetInfo:
    set_id: str
    label: str
    question_count: int
    path: pathlib.Path
    # "national_osi" | "losi_city" | None (module fragments predate this
    # field and aren't scoped to either project type).
    scope: str | None = None
    kind: str = "template"  # "template" | "custom" | "module"
    description: str | None = None
    version: str | None = None
    is_custom: bool = False
    is_master_template: bool = False


def list_question_sets(scope: str | None = None) -> list[QuestionSetInfo]:
    """Templates and modules use different metadata keys (template_id/name
    vs module_id/module) -- normalized here so callers don't need to know
    which shape a given file is.

    Pass `scope` ("national_osi" / "losi_city") to restrict to question
    sets tagged for that project type -- this is what the admin "create
    project" picker uses so a National OSI cycle only ever offers the
    national questionnaire (plus any custom sets branched from other
    national projects), never a LOSI one and vice versa. Leave it None to
    get the full registry (used by the headless /reference/question-sets
    endpoint, which has no project-type context to filter by)."""
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
            
            # Determine categorization and mutability
            if set_dir.resolve() == _CUSTOM_DIR.resolve() or path.parent.name == "custom":
                kind = "custom"
                is_custom = True
                is_master = False
            elif "templates" in path.parts or path.parent.name == "templates":
                kind = "template"
                is_custom = False
                is_master = data.get("is_master_template", True)
            else:
                kind = "module"
                is_custom = False
                is_master = False

            sets.append(
                QuestionSetInfo(
                    set_id=path.stem,
                    label=label,
                    question_count=data.get("total_questions", len(questions)),
                    path=path,
                    scope=data.get("project_type"),
                    kind=kind,
                    description=data.get("description"),
                    version=data.get("version"),
                    is_custom=is_custom,
                    is_master_template=is_master,
                )
            )
    if scope is not None:
        sets = [s for s in sets if s.scope == scope]
    return sets


def get_questionnaire_detail(set_id: str) -> dict | None:
    """Retrieve full questionnaire information including metadata, module
    distribution, and the complete normalized indicator list for inspection."""
    known = {s.set_id: s for s in list_question_sets()}
    info = known.get(set_id)
    if info is None:
        return None

    try:
        data = json.loads(info.path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    questions = data.get("questions", [])
    modules_count: dict[str, int] = {}
    evidence_loci_count: dict[str, int] = {}
    for q in questions:
        mod = q.get("module") or q.get("question_class") or "General"
        modules_count[mod] = modules_count.get(mod, 0) + 1
        locus = q.get("evidence_locus") or "national_portal_only"
        evidence_loci_count[locus] = evidence_loci_count.get(locus, 0) + 1

    return {
        "set_id": info.set_id,
        "label": info.label,
        "description": data.get("description") or info.label,
        "version": data.get("version", "1.0"),
        "scope": info.scope,
        "kind": info.kind,
        "is_custom": info.is_custom,
        "is_master_template": info.is_master_template,
        "is_deletable": info.is_custom,
        "path": str(info.path),
        "file_name": info.path.name,
        "total_questions": len(questions),
        "modules_count": modules_count,
        "evidence_loci_count": evidence_loci_count,
        "questions": questions,
    }


def delete_questionnaire(set_id: str) -> tuple[bool, str]:
    """Delete a custom questionnaire file.

    Returns (True, label) on success.
    Raises ValueError if the questionnaire is a protected system template.
    Raises FileNotFoundError if questionnaire is not found.
    """
    known = {s.set_id: s for s in list_question_sets()}
    info = known.get(set_id)
    if info is None:
        raise FileNotFoundError(f"Questionnaire '{set_id}' not found.")

    if not info.is_custom:
        raise ValueError(
            f"Cannot delete system questionnaire '{info.label}'. Standard Master Templates and modular packs are protected."
        )

    if info.path.exists():
        info.path.unlink()
        return True, info.label

    raise FileNotFoundError(f"File for questionnaire '{set_id}' was already deleted.")


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


def _question_to_template_dict(q: Question) -> dict:
    """Inverse of the question construction in load_question_set(): turns a
    live Question back into the flat dict shape the template JSON files
    use, so a saved custom set can be re-loaded by load_question_set() like
    any stock template. Strips the "<cycle_id>:" prefix load_question_set()
    and compose_question_id() add, so re-saving doesn't accumulate prefixes
    across projects. This must stay keyed off question_id, not indicator_id
    -- indicator_id ("#010"-style display codes) is NOT guaranteed unique
    within a template (module-local numbering repeats across modules), so
    using it here would collapse two distinct indicators onto the same
    saved question_id and silently drop one on the next load."""
    prefix = f"{q.cycle_id}:"
    bare_id = q.question_id[len(prefix):] if q.question_id.startswith(prefix) else q.question_id
    return {
        "question_id": bare_id,
        "indicator_id": q.indicator_id,
        "module": q.question_class,
        "title": q.title,
        "text": q.text,
        "what": q.what,
        "why": q.why,
        "how": q.how,
        "benchmark_case": q.benchmark_case,
        "reference_links": q.reference_links,
        "answer_type": q.answer_type.value,
        "evidence_locus": q.evidence_locus.value,
        "is_custom": q.is_custom,
        "requires_authenticated_access": q.requires_authenticated_access,
    }


def save_custom_question_set(
    cycle: SurveyCycle, questions: list[Question], label: str | None = None,
) -> QuestionSetInfo:
    """Persist a project's current indicator set (its starting template plus
    whatever custom indicators the admin has added, minus anything retired)
    as a new, named, reusable question set under data/questionnaires/custom/.

    This is what makes a custom indicator -- or a retirement/edit of a
    default one -- "count" beyond its own project: once saved, the set
    shows up in list_question_sets(scope=...) tagged with this cycle's
    project_type, so it's offered in the create-project picker for future
    projects of the same scope (national vs local) -- without polluting
    the other scope's options.

    `label` lets an admin give the saved set a name that carries context
    about the project (e.g. "LOSI UK 2025 — Security-Hardened Set")
    instead of always taking the auto-generated one.

    set_id is stable per cycle (not per save), so saving again after a
    later edit/retire/add overwrites the same file rather than leaving
    stale intermediate snapshots behind."""
    _CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    set_id = f"custom_{cycle.cycle_id}"
    label = label or f"{cycle.name} — Custom Indicator Set ({len(questions)} indicators)"
    data = {
        "template_id": set_id,
        "name": label,
        "description": (
            f"Custom indicator set branched from project '{cycle.name}' "
            f"({cycle.cycle_id}) after an admin added indicators beyond the "
            "starting template."
        ),
        "version": "custom",
        "is_master_template": False,
        "project_type": cycle.project_type.value,
        "total_questions": len(questions),
        "questions": [_question_to_template_dict(q) for q in questions],
    }
    path = _CUSTOM_DIR / f"{set_id}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return QuestionSetInfo(
        set_id=set_id,
        label=label,
        question_count=len(questions),
        path=path,
        scope=cycle.project_type.value,
        kind="custom",
        description=data["description"],
        version="custom",
        is_custom=True,
        is_master_template=False,
    )
