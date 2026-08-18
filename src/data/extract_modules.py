"""Extract and enrich UN Online Service Index (OSI) indicators from training decks (Modules 2.1 - 2.6).

Extracts What, Why, How (Indicative Steps), Case Examples, and Reference Links
from each module PDF in `understanding docs/` and outputs structured JSONs to
`data/questionnaires/modules/` and a consolidated `data/questionnaires/templates/un_osi_2024_master.json`.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from typing import Any

import pypdf

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "understanding docs"
OUT_DIR = REPO_ROOT / "data" / "questionnaires"
MODULES_OUT_DIR = OUT_DIR / "modules"
TEMPLATES_OUT_DIR = OUT_DIR / "templates"

MODULE_CONFIGS = [
    {
        "id": "2.1",
        "prefix": "IF",
        "name": "Institutional Framework",
        "pdf_filename": "Module 2.1 Institutional Framework (1).pdf",
        "evidence_locus_default": "national_portal_only",
    },
    {
        "id": "2.2",
        "prefix": "CP",
        "name": "Content Provision",
        "pdf_filename": "Module 2.2 Content Provision.pdf",
        "evidence_locus_default": "national_portal_only",
    },
    {
        "id": "2.3",
        "prefix": "SP",
        "name": "Service Provision",
        "pdf_filename": "Module 2.3 Service Provision.pdf",
        "evidence_locus_default": "national_portal_only",
    },
    {
        "id": "2.4",
        "prefix": "EP",
        "name": "E-Participation",
        "pdf_filename": "Module 2.4 E-Participation.pdf",
        "evidence_locus_default": "national_portal_only",
    },
    {
        "id": "2.5",
        "prefix": "TECH",
        "name": "Technology",
        "pdf_filename": "Module 2.5 Technology.pdf",
        "evidence_locus_default": "national_portal_only",
    },
    {
        "id": "2.6",
        "prefix": "EGL",
        "name": "E-Government Literacy",
        "pdf_filename": "Module 2.6 E-Government Literacy.pdf",
        "evidence_locus_default": "national_portal_only",
    },
]

# Sectors frequently expanded in UN indicators
SECTORS = ["Health", "Education", "Employment and/or Labor", "Social Protection", "Environment", "Justice"]


def _clean_text(text: str) -> str:
    if not text:
        return ""
    # Normalize multiple whitespace and line breaks
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_module_slides(pdf_path: pathlib.Path, module_cfg: dict) -> list[dict[str, Any]]:
    reader = pypdf.PdfReader(str(pdf_path))
    slides: list[dict[str, Any]] = []

    for idx in range(1, len(reader.pages)):
        raw_text = reader.pages[idx].extract_text()
        if not raw_text or not raw_text.strip():
            continue

        # Skip summary table pages (which don't contain full What/Why cards)
        if "Indicator Description" in raw_text or ("Indicator" in raw_text[:60] and "Description" in raw_text[:60]):
            continue

        # Extract What, Why, How, Case Examples
        what_m = re.search(r"What\s+(.*?)(?=Why|How\?|Case Examples|Submit your case|$)", raw_text, re.DOTALL)
        why_m = re.search(r"Why\s+(.*?)(?=How\?|Case Examples|Submit your case|$)", raw_text, re.DOTALL)
        how_m = re.search(r"How\?\s*(?:Indicative Steps:)?\s*(.*?)(?=Case Examples|Submit your case|Check out|$)", raw_text, re.DOTALL)
        cases_m = re.search(r"Case Examples\s+(.*?)(?=Submit your case|$)", raw_text, re.DOTALL)
        check_out_m = re.search(r"Check out\s+(.*?)(?=Case Examples|Submit your case|$)", raw_text, re.DOTALL)

        if not (what_m and why_m):
            continue

        codes = re.findall(r"#\d+[a-z]?", raw_text)
        # Deduplicate codes while preserving order
        unique_codes = []
        for c in codes:
            if c not in unique_codes:
                unique_codes.append(c)

        what_text = _clean_text(what_m.group(1))
        why_text = _clean_text(why_m.group(1))
        how_text = _clean_text(how_m.group(1)) if how_m else ""
        case_text = _clean_text(cases_m.group(1)) if cases_m else ""
        ref_text = _clean_text(check_out_m.group(1)) if check_out_m else ""

        # Extract title from first line or indicator line at the bottom
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        title = ""
        # Look for indicator title pattern e.g., '1. #010 Organizational structure' or '14. Legislation... (#336)'
        for line in lines:
            m = re.match(r"^\d+\.\s*(?:#\d+[a-z]?\s*)?(.*?)(?:\(#\d+.*?\))?$", line)
            if m and len(m.group(1).strip()) > 3:
                title = m.group(1).strip()
                # Clean up if title starts with codes
                title = re.sub(r"^#\d+[a-z]?\s*", "", title).strip()
                break
        if not title and lines:
            title = lines[0]

        slides.append({
            "slide_number": idx + 1,
            "codes": unique_codes,
            "title": title,
            "what": what_text,
            "why": why_text,
            "how": how_text,
            "case_examples": case_text,
            "reference_info": ref_text,
        })
    return slides


def build_questions_for_module(module_cfg: dict, slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prefix = module_cfg["prefix"]
    module_name = module_cfg["name"]
    locus_default = module_cfg["evidence_locus_default"]
    questions: list[dict[str, Any]] = []

    # Map existing extracted json if available to cross-check locus and sector breakdowns
    extracted_json_name = f"module_{module_cfg['id'].replace('.', '_')}_{module_name.lower().replace(' ', '_').replace('-', '_')}.json"
    legacy_file = DOCS_DIR / "_extracted" / extracted_json_name
    legacy_rows = []
    if legacy_file.exists():
        try:
            legacy_data = json.loads(legacy_file.read_text(encoding="utf-8"))
            legacy_rows = legacy_data.get("indicators", [])
        except Exception:
            pass

    # Build lookup by code
    legacy_by_code: dict[str, dict] = {}
    for r in legacy_rows:
        codes = r["code"] if isinstance(r["code"], list) else [r["code"]]
        for c in codes:
            legacy_by_code[c] = r

    for slide in slides:
        codes = slide["codes"]
        if not codes:
            continue

        # Check if this slide has multiple codes corresponding to sectors
        legacy_info = legacy_by_code.get(codes[0], {})
        sector_labels = legacy_info.get("sector_labels")
        evidence_locus = legacy_info.get("evidence_locus", locus_default)

        # How indicative steps formatting
        how_dict = {
            "evidence_locus": evidence_locus,
            "scoring_guidance": slide["how"],
            "criteria_for_yes": "Evidence found on the designated government portal satisfying the What specification.",
            "criteria_for_no": "No evidence found or feature unreachable within reasonable navigation.",
        }

        if sector_labels and len(sector_labels) == len(codes):
            for code, sector in zip(codes, sector_labels):
                bare = code.lstrip("#")
                qid = f"{prefix}-{bare}"
                q_title = f"{slide['title']} — {sector}" if slide['title'] else f"{module_name} {code} ({sector})"
                text = f"{q_title} — {slide['what'][:150]}" if slide['what'] else q_title

                questions.append({
                    "question_id": qid,
                    "indicator_id": code,
                    "module": module_name,
                    "title": q_title,
                    "text": text,
                    "what": slide["what"],
                    "why": slide["why"],
                    "how": how_dict,
                    "benchmark_case": slide["case_examples"],
                    "reference_links": [slide["reference_info"]] if slide["reference_info"] else [],
                    "answer_type": "binary",
                    "evidence_locus": evidence_locus,
                    "is_custom": False,
                    "requires_authenticated_access": False,
                })
        else:
            bare = codes[0].lstrip("#")
            qid = f"{prefix}-{bare}"
            ind_id = codes[0] if len(codes) == 1 else ",".join(codes)
            q_title = slide["title"] or f"{module_name} {ind_id}"
            text = f"{q_title} — {slide['what'][:150]}" if slide['what'] else q_title

            questions.append({
                "question_id": qid,
                "indicator_id": ind_id,
                "module": module_name,
                "title": q_title,
                "text": text,
                "what": slide["what"],
                "why": slide["why"],
                "how": how_dict,
                "benchmark_case": slide["case_examples"],
                "reference_links": [slide["reference_info"]] if slide["reference_info"] else [],
                "answer_type": "binary",
                "evidence_locus": evidence_locus,
                "is_custom": False,
                "requires_authenticated_access": False,
            })

    return questions


def main():
    MODULES_OUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_questions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for cfg in MODULE_CONFIGS:
        pdf_path = DOCS_DIR / cfg["pdf_filename"]
        if not pdf_path.exists():
            print(f"Warning: PDF not found: {pdf_path}")
            continue

        slides = parse_module_slides(pdf_path, cfg)
        questions = build_questions_for_module(cfg, slides)

        # Deduplicate question_id
        unique_questions = []
        for q in questions:
            if q["question_id"] in seen_ids:
                # Add suffix if duplicate
                q["question_id"] = f"{q['question_id']}-sub"
            seen_ids.add(q["question_id"])
            unique_questions.append(q)

        out_data = {
            "module": cfg["name"],
            "module_id": cfg["id"],
            "source_pdf": cfg["pdf_filename"],
            "total_questions": len(unique_questions),
            "questions": unique_questions,
        }

        filename = f"module_{cfg['id'].replace('.', '_')}_{cfg['name'].lower().replace(' ', '_').replace('-', '_')}.json"
        out_file = MODULES_OUT_DIR / filename
        out_file.write_text(json.dumps(out_data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Extracted {len(unique_questions)} questions to {out_file.name}")

        all_questions.extend(unique_questions)

    # Output Master Template
    master_template = {
        "template_id": "un_osi_2024_master",
        "name": "UN E-Government Survey 2024 — Online Service Index (OSI) Master Indicator Set",
        "description": "Standard official UN DESA OSI indicator catalog extracted from Modules 2.1 through 2.6 with complete What, Why, and How scoring criteria.",
        "version": "2024.1",
        "is_master_template": True,
        "total_questions": len(all_questions),
        "questions": all_questions,
    }

    master_path = TEMPLATES_OUT_DIR / "un_osi_2024_master.json"
    master_path.write_text(json.dumps(master_template, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSuccessfully created Master Template with {len(all_questions)} questions at {master_path}")

    # Also update data/questions/msq_indicators.json for backward compatibility
    legacy_target = REPO_ROOT / "data" / "questions" / "msq_indicators.json"
    legacy_target.write_text(json.dumps(master_template, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Updated legacy indicator file at {legacy_target.name}")


if __name__ == "__main__":
    main()
