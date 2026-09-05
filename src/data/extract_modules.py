"""Extract and enrich UN Online Service Index (OSI) and Local Online Service Index (LOSI) indicators.

Extracts What, Why, How (Indicative Steps), Case Examples, and Reference Links
from each module PDF in `understanding docs/Nationalegov questionnare/` and `understanding docs/LOSI Questionnare/`
and outputs structured JSONs to `data/questionnaires/modules/` and consolidated
master templates `data/questionnaires/templates/un_osi_2024_master.json` and
`data/questionnaires/templates/un_losi_2024_master.json`.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pypdf

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "understanding docs"
NATIONAL_DOCS_DIR = DOCS_DIR / "Nationalegov questionnare"
LOSI_DOCS_DIR = DOCS_DIR / "LOSI Questionnare"

OUT_DIR = REPO_ROOT / "data" / "questionnaires"
MODULES_OUT_DIR = OUT_DIR / "modules"
TEMPLATES_OUT_DIR = OUT_DIR / "templates"


def clean_text(text: str) -> str:
    """Normalize whitespace, ligatures, and typographic characters."""
    if not text:
        return ""
    # Ligatures
    text = (
        text.replace("\ufb00", "ff")
        .replace("\ufb01", "fi")
        .replace("\ufb02", "fl")
        .replace("\ufb03", "ffi")
        .replace("\ufb04", "ffl")
    )
    # Quotes and dashes
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2014", "—").replace("\u2013", "–")
    # Specific OCR / encoding cleanups
    text = text.replace("T?rkiye", "Türkiye").replace("o?cial", "official").replace("e?ciency", "efficiency")
    text = text.replace("e?ects", "effects").replace("identi?ed", "identified").replace("de?ne", "define")
    text = text.replace("speci?c", "specific").replace("bene?ts", "benefits").replace("?nding", "finding")
    text = text.replace("European Commission's' White Paper", "European Commission's White Paper")
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Sectors frequently expanded in UN indicators
SECTORS_6 = ["Health", "Education", "Employment", "Social Protection", "Environment", "Justice"]
SECTORS_6_IF = ["Health", "Education", "Employment and/or Labor", "Social Protection", "Environment", "Justice"]
SECTORS_6_BUDGET = ["Education", "Employment", "Environment", "Health", "Justice", "Social Protection"]

_SECTOR_KEYWORDS = [
    r"Employment(?:\s*and/or\s*Labor|\s*/\s*Labou?r)?",
    r"Health",
    r"Education",
    r"Social\s+Protection",
    r"Environment",
    r"Justice",
]
_SECTOR_ALT = "|".join(_SECTOR_KEYWORDS)
_SECTOR_SEP = r"(?:\s*[,/&]\s*|\s+and\s+|\s+or\s+)+"
_SECTOR_RUN_RE = re.compile(rf"(?:{_SECTOR_ALT})(?:{_SECTOR_SEP}(?:{_SECTOR_ALT}))+", re.IGNORECASE)


def _localize_sector_text(text: str, sector: str) -> str:
    """Replace a multi-sector enumeration in What text with a specific sector."""
    if not text:
        return text
    return _SECTOR_RUN_RE.sub(sector, text, count=1)


OSI_MODULE_CONFIGS = [
    {
        "id": "2.1",
        "prefix": "IF",
        "name": "Institutional Framework",
        "pdf_filename": "Module 2.1 Institutional Framework (3).pdf",
        "fallback_pdf": "Module 2.1 Institutional Framework (1).pdf",
        "evidence_locus_default": "national_portal_only",
        "expected_questions": 16,
    },
    {
        "id": "2.2",
        "prefix": "CP",
        "name": "Content Provision",
        "pdf_filename": "Module 2.2 Content Provision (2).pdf",
        "fallback_pdf": "Module 2.2 Content Provision.pdf",
        "evidence_locus_default": "national_portal_only",
        "expected_questions": 8,
    },
    {
        "id": "2.3",
        "prefix": "SP",
        "name": "Service Provision",
        "pdf_filename": "Module 2.3 Service Provision (1).pdf",
        "fallback_pdf": "Module 2.3 Service Provision.pdf",
        "evidence_locus_default": "national_portal_only",
        "expected_questions": 30,
    },
    {
        "id": "2.4",
        "prefix": "EP",
        "name": "E-Participation",
        "pdf_filename": "Module 2.4 E-Participation (1).pdf",
        "fallback_pdf": "Module 2.4 E-Participation.pdf",
        "evidence_locus_default": "national_portal_only",
        "expected_questions": 21,
    },
    {
        "id": "2.5",
        "prefix": "TECH",
        "name": "Technology",
        "pdf_filename": "Module 2.5 Technology (1).pdf",
        "fallback_pdf": "Module 2.5 Technology.pdf",
        "evidence_locus_default": "national_portal_only",
        "expected_questions": 14,
    },
    {
        "id": "2.6",
        "prefix": "EGL",
        "name": "E-Government Literacy",
        "pdf_filename": "Module 2.6 E-Government Literacy (1).pdf",
        "fallback_pdf": "Module 2.6 E-Government Literacy.pdf",
        "evidence_locus_default": "national_portal_only",
        "expected_questions": 13,
    },
]

OSI_SLIDE_METADATA: dict[tuple[str, int], dict[str, Any]] = {
    # Module 2.1 Institutional Framework
    ("2.1", 1): {"title": "Organization structure/chart of the government", "codes": ["#010"]},
    ("2.1", 2): {"title": "Names and titles of heads of department", "codes": ["#011"]},
    ("2.1", 3): {"title": "Links to sub-national/local government institutions/agencies", "codes": ["#012"]},
    ("2.1", 4): {"title": "Privacy statement(s)", "codes": ["#014"]},
    ("2.1", 5): {"title": "National e-Government/Digital Government Strategy", "codes": ["#342"]},
    ("2.1", 6): {"title": "Citizens' rights to access government information", "codes": ["#339"]},
    ("2.1", 7): {"title": "Legislation/law/policy/regulation on personal data protection", "codes": ["#338"]},
    ("2.1", 8): {"title": "Legislation/law/policy/regulation on cybersecurity", "codes": ["#340"]},
    ("2.1", 9): {"title": "National CIO or equivalent", "codes": ["#337"]},
    ("2.1", 10): {"title": "Legislation/law/policy/regulation on e-participation", "codes": ["#345"]},
    ("2.1", 11): {"title": "Legislation/law/policy/regulation on Open Government Data", "codes": ["#341"]},
    (
        "2.1",
        12,
    ): {
        "title": "Link to the sectoral or ministerial websites",
        "codes": ["#090", "#103", "#119", "#132", "#161", "#172"],
        "grouped": True,
        "display_code": "#090, #103, #119, #132, #161, #172",
        "locus": "any_government_domain",
    },
    (
        "2.1",
        13,
    ): {
        "title": "Information on policies related to different sectors",
        "codes": ["#091", "#104", "#120", "#133", "#162", "#173"],
        "grouped": True,
        "display_code": "#091, #104, #120, #133, #162, #173",
        "locus": "any_government_domain",
    },
    (
        "2.1",
        14,
    ): {
        "title": "Legislation/law/regulation against misinformation, disinformation and/or fake news",
        "codes": ["#336"],
    },
    ("2.1", 15): {"title": "A cloud strategy or equivalent", "codes": ["#343"]},
    ("2.1", 16): {"title": "Strategy or equivalent on the use of artificial intelligence (AI enabled)", "codes": ["#344"]},
    # Module 2.2 Content Provision
    ("2.2", 1): {"title": "Foreign language support", "codes": ["#015"]},
    ("2.2", 2): {"title": "Procurement announcements", "codes": ["#028"]},
    ("2.2", 3): {"title": "Procurement results/contracts awarded", "codes": ["#030"]},
    ("2.2", 4): {"title": "National Government portal usage statistics", "codes": ["#088"]},
    ("2.2", 5): {"title": "Available scholarships or other funding", "codes": ["#117"]},
    ("2.2", 6): {"title": "Employment for youth", "codes": ["#129"]},
    ("2.2", 7): {"title": "Workers' compensation benefits", "codes": ["#131a"]},
    ("2.2", 8): {"title": "Long term care", "codes": ["#150"]},
    # Module 2.3 Service Provision
    ("2.3", 1): {"title": "E-procurement platform", "codes": ["#029"]},
    ("2.3", 2): {"title": "Income taxes", "codes": ["#043"]},
    ("2.3", 3): {"title": "Value Added Tax, Goods & Services Tax", "codes": ["#044"]},
    ("2.3", 4): {"title": "Entry or Transit Visa", "codes": ["#045"]},
    ("2.3", 5): {"title": "Registration or renewal for a vehicle", "codes": ["#046"]},
    ("2.3", 6): {"title": "Online Police declaration", "codes": ["#047"]},
    ("2.3", 7): {"title": "Address change notification", "codes": ["#048"]},
    ("2.3", 8): {"title": "Registration for a new company or business entity", "codes": ["#049"]},
    (
        "2.3",
        9,
    ): {
        "title": "Birth /Death / Marriage certificate",
        "codes": ["#050", "#051", "#052"],
        "grouped": True,
        "display_code": "#050, #051, #052",
    },
    ("2.3", 10): {"title": "Personal Identity Cards", "codes": ["#053"]},
    ("2.3", 11): {"title": "Driver's license", "codes": ["#054"]},
    ("2.3", 12): {"title": "Online land title registration", "codes": ["#055"]},
    ("2.3", 13): {"title": "Online environment-related permit", "codes": ["#056"]},
    ("2.3", 14): {"title": "Online building permit", "codes": ["#057"]},
    ("2.3", 15): {"title": "Government vacancy positions", "codes": ["#058"]},
    ("2.3", 16): {"title": "Registration for business license", "codes": ["#059"]},
    (
        "2.3",
        17,
    ): {
        "title": "Water utility/ Energy (electricity/gas) utility",
        "codes": ["#062", "#063"],
        "grouped": True,
        "display_code": "#062-063",
    },
    ("2.3", 18): {"title": "Digital invoices", "codes": ["#079"]},
    (
        "2.3",
        19,
    ): {
        "title": "GIS data and/or online services",
        "codes": ["#080", "#081"],
        "grouped": True,
        "display_code": "#080, #081",
    },
    ("2.3", 20): {"title": "Business tax filing", "codes": ["#082"]},
    ("2.3", 21): {"title": "Transitioning people to retirement", "codes": ["#131b"]},
    (
        "2.3",
        22,
    ): {
        "title": "Online services provision for six main sectors",
        "codes": ["#095", "#108", "#124", "#137", "#166", "#177"],
        "grouped": True,
        "display_code": "#095, #108, #124, #137, #166, #177",
    },
    (
        "2.3",
        23,
    ): {
        "title": "Mobile services for six main sectors",
        "codes": ["#095a", "#108a", "#124a", "#137a", "#166a", "#177a"],
        "grouped": True,
        "display_code": "#095a, #108a, #124a, #137a, #166a, #177a",
    },
    (
        "2.3",
        24,
    ): {
        "title": "SMS alert for six main sectors",
        "codes": ["#095b", "#108b", "#124b", "#137b", "#166b", "#177b"],
        "grouped": True,
        "display_code": "#095b, #108b, #124b, #137b, #166b, #177b",
    },
    (
        "2.3",
        25,
    ): {
        "title": "Scholarships, fellowships or other forms of government funding",
        "codes": ["#117", "#118"],
        "grouped": True,
        "display_code": "#117, #118",
    },
    (
        "2.3",
        26,
    ): {
        "title": "Specific Services/ Information available for vulnerable groups",
        "codes": ["#143", "#144", "#145", "#146", "#147", "#148"],
        "grouped": True,
        "display_code": "#143, #144, #145, #146, #147, #148",
    },
    ("2.3", 27): {"title": "Application for citizenship or residentship", "codes": ["#149"]},
    ("2.3", 28): {"title": "Affidavit of criminal record/background clearance", "codes": ["#182"]},
    ("2.3", 29): {"title": "Access to justice information", "codes": ["#183"]},
    (
        "2.3",
        30,
    ): {
        "title": "Benefits Application",
        "codes": ["#184", "#185", "#189", "#190", "#191"],
        "grouped": True,
        "display_code": "#184, #185, #189, #190, #191",
    },
    # Module 2.4 E-Participation
    ("2.4", 1): {"title": "Corruption Reporting", "codes": ["#021"]},
    ("2.4", 2): {"title": "Calendar on e-participation activities", "codes": ["#033"]},
    ("2.4", 3): {"title": "Online tools for policy", "codes": ["#034"]},
    ("2.4", 4): {"title": "Open government data portal", "codes": ["#037"]},
    ("2.4", 5): {"title": "New open datasets requests", "codes": ["#040"]},
    ("2.4", 6): {"title": "Open Government Data events", "codes": ["#042"]},
    ("2.4", 7): {"title": "Open Datasets on government expenditures", "codes": ["#078"]},
    (
        "2.4",
        8,
    ): {
        "title": "Government expenditures for 6 sectors",
        "codes": ["#092", "#105", "#121", "#134", "#163", "#174"],
        "grouped": True,
        "display_code": "#092, #105, #121, #134, #163, #174",
    },
    (
        "2.4",
        9,
    ): {
        "title": "Online consultations for 6 sectors",
        "codes": ["#096", "#109", "#125", "#138", "#167", "#178"],
        "grouped": True,
        "display_code": "#096, #109, #125, #138, #167, #178",
    },
    (
        "2.4",
        10,
    ): {
        "title": "Inclusion of voices in decision making in 6 sectors",
        "codes": ["#098", "#111", "#127", "#140", "#169", "#180"],
        "grouped": True,
        "display_code": "#098, #111, #127, #140, #169, #180",
    },
    (
        "2.4",
        11,
    ): {
        "title": "Open government datasets for 6 sectors",
        "codes": ["#099", "#112", "#128", "#141", "#170", "#181"],
        "grouped": True,
        "display_code": "#099, #112, #128, #141, #170, #181",
    },
    ("2.4", 12): {"title": "Labor laws violation report", "codes": ["#131"]},
    ("2.4", 13): {"title": "Participatory budgeting", "codes": ["#193"]},
    ("2.4", 14): {"title": "E-participation portal(s)", "codes": ["#302"]},
    ("2.4", 15): {"title": "Open data license", "codes": ["#303"]},
    (
        "2.4",
        16,
    ): {
        "title": "Budget expenditure datasets for 6 sectors",
        "codes": ["#304", "#305", "#306", "#307", "#308", "#309"],
        "grouped": True,
        "display_code": "#304, #305, #306, #307, #308, #309",
    },
    ("2.4", 17): {"title": "Real time open government datasets", "codes": ["#310"]},
    ("2.4", 18): {"title": "Online services for rural areas", "codes": ["#313"]},
    ("2.4", 19): {"title": "E-petition", "codes": ["#323"]},
    (
        "2.4",
        20,
    ): {
        "title": "Policy-decision making for vulnerable groups",
        "codes": ["#324", "#325", "#326", "#327", "#328", "#329"],
        "grouped": True,
        "display_code": "#324, #325, #326, #327, #328, #329",
    },
    (
        "2.4",
        21,
    ): {
        "title": "Online consultations for vulnerable groups",
        "codes": ["#330", "#331", "#332", "#333", "#334", "#335"],
        "grouped": True,
        "display_code": "#330, #331, #332, #333, #334, #335",
    },
    # Module 2.5 Technology
    ("2.5", 1): {"title": "Government portal ease of finding", "codes": ["#002"]},
    ("2.5", 2): {"title": "Advanced search options", "codes": ["#004"]},
    ("2.5", 3): {"title": "Sitemap/Index", "codes": ["#005"]},
    ("2.5", 4): {"title": "Contact Details", "codes": ["#008"]},
    (
        "2.5",
        5,
    ): {
        "title": "Accessibility by citizens/businesses to own data",
        "codes": ["#022", "#024"],
        "grouped": True,
        "display_code": "#022-024",
    },
    (
        "2.5",
        6,
    ): {
        "title": "Possibility for citizens/businesses to modify own data",
        "codes": ["#023", "#025"],
        "grouped": True,
        "display_code": "#023-025",
    },
    ("2.5", 7): {"title": "Responsive web design", "codes": ["#071"]},
    ("2.5", 8): {"title": "Evidence of being updated in the past month", "codes": ["#072"]},
    ("2.5", 9): {"title": "National portal(s) utilize HTTPS", "codes": ["#074"]},
    ("2.5", 10): {"title": "Save part of the transaction and access later", "codes": ["#083"]},
    ("2.5", 11): {"title": "Access to list of previous interactions/transactions", "codes": ["#087"]},
    ("2.5", 12): {"title": "Availability of AI-enabled chat-bot functionality", "codes": ["#09a"]},
    ("2.5", 13): {"title": "Compliant with W3C standards (CSS style sheet)", "codes": ["#195"]},
    ("2.5", 14): {"title": "Compliant with W3C standards (markup validity)", "codes": ["#196"]},
    # Module 2.6 E-Government Literacy
    ("2.6", 1): {"title": "Search feature", "codes": ["#003"]},
    ("2.6", 2): {"title": "Help feature/FAQs section", "codes": ["#006"]},
    ("2.6", 3): {"title": "Social networking features", "codes": ["#007"]},
    ("2.6", 4): {"title": "Live chat support with a person", "codes": ["#009"]},
    ("2.6", 5): {"title": "Privacy policy", "codes": ["#014"]},
    ("2.6", 6): {"title": "Information on online services use", "codes": ["#016"]},
    ("2.6", 7): {"title": "Digital ID to access online services", "codes": ["#017"]},
    ("2.6", 8): {"title": "Facilitation of free Internet access", "codes": ["#036a"]},
    ("2.6", 9): {"title": "Access to physical spaces for online services", "codes": ["#036b"]},
    ("2.6", 10): {"title": "Open data metadata", "codes": ["#038"]},
    ("2.6", 11): {"title": "Guidance on Open Government datasets", "codes": ["#039"]},
    ("2.6", 12): {"title": "Mark favorite/most used online services", "codes": ["#086"]},
    (
        "2.6",
        13,
    ): {
        "title": "Co-creation of e-services",
        "codes": ["#317", "#318", "#319", "#320", "#321", "#322"],
        "grouped": True,
        "display_code": "#317, #318, #319, #320, #321, #322",
    },
}


def find_pdf_path(pdf_filename: str, fallback_filename: str | None = None, is_losi: bool = False) -> pathlib.Path | None:
    search_dirs = [LOSI_DOCS_DIR, DOCS_DIR] if is_losi else [NATIONAL_DOCS_DIR, DOCS_DIR]
    for d in search_dirs:
        p = d / pdf_filename
        if p.exists():
            return p
        if fallback_filename:
            fb = d / fallback_filename
            if fb.exists():
                return fb
    return None


def extract_osi_module(module_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    m_id = module_cfg["id"]
    m_prefix = module_cfg["prefix"]
    m_name = module_cfg["name"]
    m_locus = module_cfg["evidence_locus_default"]

    pdf_path = find_pdf_path(module_cfg["pdf_filename"], module_cfg.get("fallback_pdf"), is_losi=False)
    if not pdf_path or not pdf_path.exists():
        print(f"Warning: PDF not found for Module {m_id}: {module_cfg['pdf_filename']}")
        return []

    reader = pypdf.PdfReader(str(pdf_path))
    slide_idx = 0
    questions: list[dict[str, Any]] = []

    for p_idx in range(1, len(reader.pages)):
        raw_text = reader.pages[p_idx].extract_text() or ""
        text = clean_text(raw_text)
        if "Indicator Description" in text or ("Indicator" in text[:60] and "Description" in text[:60]):
            continue
        if "What" not in text or "Why" not in text:
            continue

        slide_idx += 1
        meta = OSI_SLIDE_METADATA.get((m_id, slide_idx), {})

        # Extract fields
        what_m = re.search(r"What\s+(.*?)(?=Why|How\?|Case Examples|Check out|Submit your case|$)", text, re.DOTALL)
        why_m = re.search(r"Why\s+(.*?)(?=How\?|Case Examples|Check out|Submit your case|$)", text, re.DOTALL)
        how_m = re.search(
            r"How\?\s*(?:Indicative [sS]teps:?)?\s*(.*?)(?=Case Examples|Check out|Submit your case|$)",
            text,
            re.DOTALL,
        )
        cases_m = re.search(r"Case Examples\s+(.*?)(?=Check out|Submit your case|$)", text, re.DOTALL)
        check_out_m = re.search(r"Check out\s+(.*?)(?=Case Examples|Submit your case|$)", text, re.DOTALL)

        what_text = clean_text(what_m.group(1)) if what_m else ""
        why_text = clean_text(why_m.group(1)) if why_m else ""
        how_text = clean_text(how_m.group(1)) if how_m else ""
        case_text = clean_text(cases_m.group(1)) if cases_m else ""
        ref_text = clean_text(check_out_m.group(1)) if check_out_m else ""

        title = meta.get("title", f"{m_name} #{slide_idx}")
        codes = meta.get("codes", [f"#{str(slide_idx).zfill(3)}"])
        sectors = meta.get("sectors")
        locus = meta.get("locus", m_locus)
        is_grouped = meta.get("grouped", False)
        display_code = meta.get("display_code")

        how_dict = {
            "evidence_locus": locus,
            "scoring_guidance": how_text,
            "criteria_for_yes": "Evidence found on the designated government portal satisfying the What specification.",
            "criteria_for_no": "No evidence found or feature unreachable within reasonable navigation.",
        }

        if sectors and not is_grouped and len(sectors) == len(codes):
            for code, sector in zip(codes, sectors):
                bare = code.lstrip("#")
                qid = f"{m_prefix}-{bare}"
                q_title = f"{title} — {sector}"
                sector_what = _localize_sector_text(what_text, sector)
                q_text = f"{q_title} — {sector_what}" if sector_what else q_title

                questions.append({
                    "question_id": qid,
                    "indicator_id": code,
                    "module": m_name,
                    "title": q_title,
                    "text": q_text,
                    "what": sector_what,
                    "why": why_text,
                    "how": how_dict,
                    "benchmark_case": case_text,
                    "reference_links": [ref_text] if ref_text else [],
                    "answer_type": "binary",
                    "evidence_locus": locus,
                    "is_custom": False,
                    "requires_authenticated_access": False,
                })
        else:
            bare = codes[0].lstrip("#")
            qid = f"{m_prefix}-{bare}"
            ind_id = display_code if display_code else (codes[0] if len(codes) == 1 else ", ".join(codes))
            q_text = f"{title} — {what_text}" if what_text else title

            questions.append({
                "question_id": qid,
                "indicator_id": ind_id,
                "module": m_name,
                "title": title,
                "text": q_text,
                "what": what_text,
                "why": why_text,
                "how": how_dict,
                "benchmark_case": case_text,
                "reference_links": [ref_text] if ref_text else [],
                "answer_type": "binary",
                "evidence_locus": locus,
                "is_custom": False,
                "requires_authenticated_access": False,
            })

    return questions


LOSI_MODULE_CONFIGS = [
    {
        "id": "2.1",
        "prefix": "L-IF",
        "name": "Institutional Framework",
        "pdf_filename": "Module 2.1 Institutional framework (2).pdf",
        "evidence_locus_default": "national_portal_only",
    },
    {
        "id": "2.2",
        "prefix": "L-CP",
        "name": "Content Provision",
        "pdf_filename": "Module 2.2 Content provision (1).pdf",
        "evidence_locus_default": "national_portal_only",
    },
    {
        "id": "2.3",
        "prefix": "L-SP",
        "name": "Services Provision",
        "pdf_filename": "Module 2.3 Services Provision.pdf",
        "evidence_locus_default": "national_portal_only",
    },
    {
        "id": "2.4",
        "prefix": "L-PE",
        "name": "Participation and Engagement",
        "pdf_filename": "Module 2.4 Participation and Engagement.pdf",
        "evidence_locus_default": "national_portal_only",
    },
    {
        "id": "2.5",
        "prefix": "L-EGL",
        "name": "E-Government Literacy",
        "pdf_filename": "Module 2.5 E-Government Literacy.pdf",
        "evidence_locus_default": "national_portal_only",
    },
    {
        "id": "2.6",
        "prefix": "L-TECH",
        "name": "Technology",
        "pdf_filename": "Module 2.6 Technology.pdf",
        "evidence_locus_default": "national_portal_only",
    },
]


def extract_losi_module(module_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    m_prefix = module_cfg["prefix"]
    m_name = module_cfg["name"]
    m_locus = module_cfg["evidence_locus_default"]

    pdf_path = find_pdf_path(module_cfg["pdf_filename"], is_losi=True)
    if not pdf_path or not pdf_path.exists():
        print(f"Warning: LOSI PDF not found: {module_cfg['pdf_filename']}")
        return []

    reader = pypdf.PdfReader(str(pdf_path))
    slide_idx = 0
    questions: list[dict[str, Any]] = []

    for p_idx in range(1, len(reader.pages)):
        raw_text = reader.pages[p_idx].extract_text() or ""
        text = clean_text(raw_text)
        if "Indicator Description" in text or ("Indicator" in text[:60] and "Description" in text[:60]):
            continue
        if "What" not in text or "Why" not in text:
            continue

        slide_idx += 1

        top_m = re.search(r"^\s*(\d+\.\s*.*?)(?=\s*What\b)", text, re.DOTALL)
        bottom_m = re.search(r"Submit your case(?: here)?\s*\n\s*(\d+\.\s*.*?)$", text, re.DOTALL)
        markers = list(re.finditer(r"(?:^|\n)\s*(\d+\.\s*.*?(?:#|\(\s*#).*?)$", text, re.DOTALL))
        title_raw = (
            top_m.group(1).strip()
            if (top_m and top_m.group(1).strip())
            else (
                bottom_m.group(1).strip()
                if (bottom_m and bottom_m.group(1).strip())
                else (markers[-1].group(1).strip() if markers else "")
            )
        )
        title_clean = re.sub(r"^\d+\.\s*", "", title_raw)
        title_clean = re.sub(r"\(?\s*#?\s*[\d\w,\s-]+\s*\)?", "", title_clean).strip()
        title_clean = re.sub(r"^#?\d+[a-z]?\s*", "", title_clean).strip()
        if not title_clean:
            title_clean = f"{m_name} Indicator {slide_idx}"

        code_matches = re.findall(r"#\s*(\d+[a-z]?)", text)
        if not code_matches:
            code_matches = [str(slide_idx).zfill(3)]
        code_str = f"#{code_matches[0]}" if not code_matches[0].startswith("#") else code_matches[0]

        what_m = re.search(r"What\s+(.*?)(?=Why|How\?|Case Examples|Check out|Submit your case|$)", text, re.DOTALL)
        why_m = re.search(r"Why\s+(.*?)(?=How\?|Case Examples|Check out|Submit your case|$)", text, re.DOTALL)
        how_m = re.search(
            r"How\?\s*(?:Indicative [sS]teps:?)?\s*(.*?)(?=Case Examples|Check out|Submit your case|$)",
            text,
            re.DOTALL,
        )
        cases_m = re.search(r"Case Examples\s+(.*?)(?=Check out|Submit your case|$)", text, re.DOTALL)
        check_out_m = re.search(r"Check out\s+(.*?)(?=Case Examples|Submit your case|$)", text, re.DOTALL)

        what_text = clean_text(what_m.group(1)) if what_m else ""
        why_text = clean_text(why_m.group(1)) if why_m else ""
        how_text = clean_text(how_m.group(1)) if how_m else ""
        case_text = clean_text(cases_m.group(1)) if cases_m else ""
        ref_text = clean_text(check_out_m.group(1)) if check_out_m else ""

        bare = code_str.lstrip("#")
        qid = f"{m_prefix}-{bare}"
        q_text = f"{title_clean} — {what_text}" if what_text else title_clean

        how_dict = {
            "evidence_locus": m_locus,
            "scoring_guidance": how_text,
            "criteria_for_yes": "Evidence found on the designated municipal portal satisfying the What specification.",
            "criteria_for_no": "No evidence found or feature unreachable within reasonable navigation.",
        }

        questions.append({
            "question_id": qid,
            "indicator_id": code_str,
            "module": m_name,
            "title": title_clean,
            "text": q_text,
            "what": what_text,
            "why": why_text,
            "how": how_dict,
            "benchmark_case": case_text,
            "reference_links": [ref_text] if ref_text else [],
            "answer_type": "binary",
            "evidence_locus": m_locus,
            "is_custom": False,
            "requires_authenticated_access": False,
        })

    return questions


def main() -> None:
    MODULES_OUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=================================================================")
    print("Extracting and Rebuilding UN OSI Questionnaire (National Level)...")
    print("=================================================================")

    all_osi_questions: list[dict[str, Any]] = []

    for cfg in OSI_MODULE_CONFIGS:
        questions = extract_osi_module(cfg)
        expected = cfg["expected_questions"]
        print(f"Module {cfg['id']} ({cfg['name']}): extracted {len(questions)} questions (expected {expected})")
        if len(questions) != expected:
            raise ValueError(f"Indicator count mismatch in Module {cfg['id']}: expected {expected}, got {len(questions)}")

        out_data = {
            "module": cfg["name"],
            "module_id": cfg["id"],
            "source_pdf": cfg["pdf_filename"],
            "total_questions": len(questions),
            "questions": questions,
        }

        filename = f"module_{cfg['id'].replace('.', '_')}_{cfg['name'].lower().replace(' ', '_').replace('-', '_')}.json"
        out_file = MODULES_OUT_DIR / filename
        out_file.write_text(json.dumps(out_data, indent=2, ensure_ascii=False), encoding="utf-8")
        all_osi_questions.extend(questions)

    # Write Master Template
    master_template = {
        "template_id": "un_osi_2024_master",
        "name": "UN E-Government Survey 2024 — Online Service Index (OSI) Master Indicator Set",
        "description": "Standard official UN DESA OSI indicator catalog extracted from Modules 2.1 through 2.6 with complete What, Why, and How scoring criteria.",
        "version": "2024.1",
        "is_master_template": True,
        "total_questions": len(all_osi_questions),
        "questions": all_osi_questions,
    }

    master_path = TEMPLATES_OUT_DIR / "un_osi_2024_master.json"
    master_path.write_text(json.dumps(master_template, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSuccessfully created UN OSI Master Template with {len(all_osi_questions)} questions at {master_path}")

    # Legacy compatibility copy
    legacy_target = REPO_ROOT / "data" / "questions" / "msq_indicators.json"
    legacy_target.parent.mkdir(parents=True, exist_ok=True)
    legacy_target.write_text(json.dumps(master_template, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Updated legacy indicator copy at {legacy_target.relative_to(REPO_ROOT)}")

    # Extract LOSI Master Template if LOSI PDFs present
    if LOSI_DOCS_DIR.exists():
        print("\n=================================================================")
        print("Extracting UN LOSI Questionnaire (Municipal Level)...")
        print("=================================================================")
        all_losi_questions: list[dict[str, Any]] = []
        for cfg in LOSI_MODULE_CONFIGS:
            l_qs = extract_losi_module(cfg)
            print(f"LOSI Module {cfg['id']} ({cfg['name']}): extracted {len(l_qs)} indicators")
            all_losi_questions.extend(l_qs)

        losi_template = {
            "template_id": "un_losi_2024_master",
            "name": "UN E-Government Survey 2024 — Local Online Service Index (LOSI) Master Indicator Set",
            "description": "Official UN DESA Local Online Service Index (LOSI) municipal indicator catalog extracted from city evaluation modules.",
            "version": "2024.1",
            "is_master_template": False,
            "total_questions": len(all_losi_questions),
            "questions": all_losi_questions,
        }
        losi_path = TEMPLATES_OUT_DIR / "un_losi_2024_master.json"
        losi_path.write_text(json.dumps(losi_template, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Successfully created UN LOSI Master Template with {len(all_losi_questions)} questions at {losi_path}")


if __name__ == "__main__":
    main()
