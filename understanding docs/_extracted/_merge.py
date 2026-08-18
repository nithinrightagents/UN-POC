"""One-off merge script: combines the six extracted UN MSQ module JSON files
into data/questions/msq_indicators.json, replacing the old 10-question
heuristic demo set. Not part of the app -- run once, then can be deleted."""
import json
import pathlib

_HERE = pathlib.Path(__file__).parent
_REPO_ROOT = _HERE.parents[1]

_MODULES = [
    ("module_2_1_institutional_framework.json", "IF"),
    ("module_2_2_content_provision.json", "CP"),
    ("module_2_3_service_provision.json", "SP"),
    ("module_2_4_eparticipation.json", "EP"),
    ("module_2_5_technology.json", "TECH"),
    ("module_2_6_egov_literacy.json", "EGL"),
]

questions = []
seen_qids = set()

for filename, prefix in _MODULES:
    data = json.loads((_HERE / filename).read_text(encoding="utf-8"))
    module_name = data["module"]
    for row in data["indicators"]:
        codes = row["code"] if isinstance(row["code"], list) else [row["code"]]
        sector_labels = row.get("sector_labels")
        title = row["title"]
        description = row["description"]
        answer_type = row["answer_type"]
        evidence_locus = row["evidence_locus"]

        if sector_labels and len(sector_labels) == len(codes):
            # One question per sector -- these are genuinely distinct
            # per-sector assessment items sharing one indicator family.
            for code, sector in zip(codes, sector_labels):
                bare = code.lstrip("#")
                qid = f"{prefix}-{bare}"
                text = f"{title} — {sector} — {description}"
                questions.append({
                    "question_id": qid,
                    "indicator_id": code,
                    "text": text,
                    "answer_type": answer_type,
                    "evidence_locus": evidence_locus,
                    "module": module_name,
                })
        else:
            # One combined question per summary-table row, exactly as the
            # source deck presents it to a human assessor -- even when a
            # row bundles several UN indicator codes together.
            bare = codes[0].lstrip("#")
            qid = f"{prefix}-{bare}"
            indicator_id = codes[0] if len(codes) == 1 else ",".join(codes)
            text = f"{title} — {description}"
            questions.append({
                "question_id": qid,
                "indicator_id": indicator_id,
                "text": text,
                "answer_type": answer_type,
                "evidence_locus": evidence_locus,
                "module": module_name,
            })

for q in questions:
    if q["question_id"] in seen_qids:
        raise SystemExit(f"duplicate question_id: {q['question_id']}")
    seen_qids.add(q["question_id"])

out = {
    "questionnaire": "UN E-Government Survey — Member State Questionnaire (MSQ), Modules 2.1-2.6",
    "source": (
        "UN DESA training deck PDFs supplied by the user in `understanding docs/` "
        "(Module 2.1 Institutional Framework, 2.2 Content Provision, 2.3 Service "
        "Provision, 2.4 E-Participation, 2.5 Technology, 2.6 E-Government "
        "Literacy). Indicator codes (#NNN) are the UN's own EGDI indicator "
        "numbering. Sector-breakdown indicators (one code per sector) are "
        "expanded into one question per sector. Rows that bundle several codes "
        "without a per-sector breakdown are kept as one combined question, "
        "matching how the source deck presents them as a single assessment "
        "item. AI pre-fill only has real detection logic for a handful of "
        "indicators (see agents/prefill/heuristic.py); the rest get a dummy "
        "placeholder pre-fill result pending an LLM-based checker."
    ),
    "questions": questions,
}

out_path = _REPO_ROOT / "data" / "questions" / "msq_indicators.json"
out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Wrote {len(questions)} questions to {out_path}")
