"""The Assessor Agent (FR-008–FR-013, FR-108).

One independent evaluation of one question against one target portal.
Each call is structurally isolated: a fresh ModelProvider.generate() call
(fresh genai.Client, research R2) with no state shared across agent
indices, and each agent independently fetches the page itself rather than
sharing a centrally-fetched copy -- matching the crawl-volume assumption
in research R6 (N agent fetches per unit, on top of which verification
roughly doubles the total).

Divergence (research R7) is bound here: model, temperature, and prompt
profile are selected per `agent_index` from settings, so identically-
isolated agents still produce genuinely different reads of an ambiguous
page.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from core.base_agent import BaseAgent
from orchestration.routers.confidence_gate import ConfidenceGateOutcome, run_with_confidence_gate
from shared.prompts.profiles import build_prompt
from core.llm_factory import ModelProvider, estimate_cost
from shared.state.schemas import (
    AssessorAgentInput,
    AssessorAgentOutput,
    ElementReferenceOutput,
    EvidenceOutput,
    RetryAddendum,
)
from shared.config.settings import Settings
from shared.state.entities import AgentRunState, AssessorAgentRun, new_id, utcnow
from shared.tools.boundaries import check_authentication_boundary
from shared.tools.browser import BrowserSession
from shared.tools.capture import capture_region
from shared.tools.element_ref import build_reference, search_by_text
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.langsmith_tracing import agent_trace
from core.telemetry.stage_events import StageEventLog


_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "boolean"},
        "confidence": {"type": "integer"},
        "justification": {"type": "string"},
        "evidence_quote": {
            "type": "string",
            "description": "The exact short text snippet from the page that is the evidence. "
            "REQUIRED even when the answer is negative (feature not found) -- in that case, "
            "quote the most relevant heading or passage on the page closest to where the "
            "feature would appear, to anchor the negative finding to a specific location.",
        },
        "detected_language": {
            "type": "string",
            "description": "ISO 639-1 two-letter code of the language the PAGE CONTENT is "
            "written in (not the language of this question), e.g. 'en', 'fr', 'ar'. "
            "Use 'unknown' if it cannot be determined.",
        },
        "fill_gap_reason": {
            "type": "string",
            "description": "Debugging field, separate from `justification`. If `answer` is "
            "anything other than a confident Yes, name the SPECIFIC thing that blocked a Yes, "
            "in one short phrase, e.g.: 'not present anywhere on this page', 'this page is the "
            "wrong page for the indicator (a generic hub/topics page, not the specific one "
            "needed)', 'only a text/list equivalent exists, no diagram or visual format as "
            "literally described', 'requires authenticated access', 'evidence exists but is not "
            "on this exact portal/subdomain'. Pick the closest fit -- do not invent a new "
            "category if one of these already applies. If `answer` is a confident Yes, set this "
            "to an empty string.",
        },
        "link_likely_wrong": {
            "type": "boolean",
            "description": "True ONLY when this page is the WRONG page/link for this question "
            "-- e.g. a generic hub/topics/homepage instead of the specific page needed, or a "
            "page whose content is clearly about a different topic entirely, such that a "
            "DIFFERENT link on this same portal would plausibly answer the question. Do NOT "
            "set this true just because the feature is genuinely absent from an otherwise-"
            "relevant, correct page -- that is a legitimate negative finding, not a bad link. "
            "Always false when `answer` is a confident Yes.",
        },
        "follow_link_index": {
            "type": "integer",
            "description": "If you could NOT find enough evidence on THIS page to answer "
            "confidently, and the AVAILABLE LINKS list (below the page content) contains a "
            "specific link that plausibly leads directly to the content this question needs "
            "(e.g. this page is a category/topic hub and one link leads to the specific "
            "service), set this to that link's number. Otherwise always -1 -- including "
            "whenever you already found clear evidence for a Yes, or a confident, "
            "well-evidenced No, on this page. Never guess a link just because none seem "
            "perfect; -1 is always safe.",
        },
    },
    "required": [
        "answer",
        "confidence",
        "justification",
        "evidence_quote",
        "detected_language",
        "fill_gap_reason",
        "link_likely_wrong",
        "follow_link_index",
    ],
}


class AuthenticationBoundaryDetected(Exception):
    """Raised internally, caught by run_assessor_agent -- not a pipeline error."""


async def run_assessor_agent(
    *,
    session_id: str,
    question: dict,
    portal_url: str,
    agent_index: int,
    round_number: int,
    settings: Settings,
    provider: ModelProvider,
    browser: BrowserSession,
    fetch_log: FetchLog,
    stage_log: StageEventLog,
    cost_ledger: CostLedger,
    capture_dir: str,
    addendum: RetryAddendum | None = None,
    portal_id: str | None = None,
) -> AssessorAgentRun:
    """Runs one full Assessor Agent attempt (including the confidence gate's
    internal retries) and returns a persisted-ready AssessorAgentRun.

    `portal_url` is the live page fetched for this attempt. `portal_id` is
    the stable TargetPortal identity persisted on the resulting run (falls
    back to `portal_url` when omitted, for callers -- e.g. existing tests --
    that only deal with a single URL and have no separate stable id)."""

    model = settings.agent_models[agent_index]
    temperature = (
        settings.agent_temperatures[agent_index]
        if agent_index < len(settings.agent_temperatures)
        else 0.3
    )
    profile = (
        settings.agent_prompt_profiles[agent_index]
        if agent_index < len(settings.agent_prompt_profiles)
        else "literal"
    )

    unit_ref = {"question_id": question["question_id"], "portal_id": portal_url}

    # LangSmith tracing (FR-T-002, FR-T-005): assessor_agent child span
    async with agent_trace(agent_index, round_number, model, temperature, profile) as agent_span:
        async def assess_once(current_addendum: RetryAddendum | None) -> AssessorAgentOutput:
            with stage_log.timed("assessor_run", unit_ref, agent_index=agent_index, round_number=round_number):
                page_result, page = await browser.fetch(
                    portal_url, "assessor_agent", fetch_log,
                    timeout_ms=settings.page_navigation_timeout_ms,
                )

                if not page_result.reachable or page is None:
                    return AssessorAgentOutput(
                        answer=None,
                        confidence=0,
                        justification=f"Portal unreachable: {page_result.reason}",
                        evidence=None,
                        portal_unreachable=True,
                        model_identity=f"vertexai/{model}",
                        fill_gap_reason="portal unreachable before content could be evaluated",
                    )

                try:
                    boundary = check_authentication_boundary(page_result.final_url, page_result.html)
                    if boundary.is_authentication_boundary:
                        return AssessorAgentOutput(
                            answer=None,
                            confidence=0,
                            justification=f"Authentication boundary detected ({boundary.signal}): "
                            f"{boundary.detail}",
                            evidence=None,
                            auth_boundary_observed=True,
                            auth_boundary_url=page_result.final_url,
                            model_identity=f"vertexai/{model}",
                            fill_gap_reason="requires authenticated access",
                        )

                    output, follow_url = await _evaluate_page(
                        page_result, page, question, profile, current_addendum,
                        provider, model, temperature, capture_dir, cost_ledger, agent_index,
                        allow_navigation=True,
                    )

                    # One-hop navigation (2026-08-20 debugging pass, phase 1):
                    # the model named a same-domain link it believes leads to
                    # the actual content this page (a category/hub page)
                    # lacked. Capped at a single hop -- allow_navigation=False
                    # on the follow-up means the model cannot chain a second
                    # hop from there, bounding worst-case cost to 2x fetches
                    # and 2x model calls per attempt instead of unbounded.
                    if follow_url:
                        nav_result, nav_page = await browser.fetch(
                            follow_url, "assessor_agent", fetch_log,
                            timeout_ms=settings.page_navigation_timeout_ms,
                        )
                        if nav_result.reachable and nav_page is not None:
                            try:
                                nav_boundary = check_authentication_boundary(
                                    nav_result.final_url, nav_result.html
                                )
                                if not nav_boundary.is_authentication_boundary:
                                    nav_output, _ = await _evaluate_page(
                                        nav_result, nav_page, question, profile, current_addendum,
                                        provider, model, temperature, capture_dir, cost_ledger, agent_index,
                                        allow_navigation=False,
                                    )
                                    nav_output.navigated_to_url = follow_url
                                    output = nav_output
                                # else: an auth wall one hop deep isn't worth
                                # chasing -- keep the landing page's output.
                            finally:
                                await browser.close_page(nav_page)
                        # else: the nominated link was itself dead/unreachable
                        # -- keep the landing page's output rather than fail
                        # the whole attempt over a bad navigation guess.

                    return output
                finally:
                    await browser.close_page(page)

        outcome: ConfidenceGateOutcome = await run_with_confidence_gate(
            assess_once, settings.confidence_acceptance_threshold, settings.confidence_retry_limit
        )

        output = outcome.output
        evidence_artifact_id = None  # bound by the caller once persisted via persistence layer

        run = AssessorAgentRun(
            run_id=new_id("run"),
            session_id=session_id,
            question_id=question["question_id"],
            portal_id=portal_id or portal_url,
            agent_index=agent_index,
            round_number=round_number,
            answer=output.answer,
            confidence=output.confidence,
            justification=output.justification,
            evidence_artifact_id=evidence_artifact_id,
            confidence_retry_count=outcome.confidence_retry_count,
            state=AgentRunState.ASSESSED,
            auth_boundary_observed=output.auth_boundary_observed,
            auth_boundary_url=output.auth_boundary_url,
            portal_unreachable=output.portal_unreachable,
            model_identity=output.model_identity,
            below_acceptance_threshold=outcome.below_acceptance_threshold,
            detected_language=output.detected_language,
            fill_gap_reason=output.fill_gap_reason,
            link_likely_wrong=output.link_likely_wrong,
            raw_evidence_quote=output.raw_evidence_quote,
            evidence_located=output.evidence_located,
            navigated_to_url=output.navigated_to_url,
        )
        # Stash the raw evidence output for the caller (persistence needs a
        # standalone EvidenceArtifact record + artifact_id before it can be
        # attached to `run`); see orchestration/scheduler.py.
        run._pending_evidence = output.evidence  # type: ignore[attr-defined]
        agent_span.patch(outputs={
            "answer": run.answer,
            "confidence": run.confidence,
            "state": run.state.value,
            "auth_boundary_observed": run.auth_boundary_observed,
            "detected_language": run.detected_language,
        })
        return run



_MAX_LINK_CANDIDATES = 20


async def _extract_same_domain_links(page, base_url: str) -> list[dict]:
    """One-hop navigation (2026-08-20 debugging pass, phase 1): pulls the
    same-domain links actually present on the rendered page, so the model
    can name a concrete next step instead of only self-reporting `this page
    is wrong` (which `link_likely_wrong` asked for and got zero times in 50
    questions across two runs -- it gave the model nothing to act on).
    Best-effort: an extraction failure here should never fail the whole
    assessment, just leave the model without a navigation option."""
    try:
        raw_links = await page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({text: e.innerText.trim(), href: e.href}))",
        )
    except Exception:  # noqa: BLE001 -- best-effort only
        return []

    base_domain = urlparse(base_url).netloc.lower()
    seen: set[str] = set()
    candidates: list[dict] = []
    for link in raw_links:
        href = str(link.get("href") or "")
        text = str(link.get("text") or "").strip()
        if not href or not text or href in seen:
            continue
        if not href.startswith(("http://", "https://")):
            continue
        if urlparse(href).netloc.lower() != base_domain:
            continue
        seen.add(href)
        candidates.append({"text": text[:80], "href": href})

    # Confirmed live on borger.dk's education hub: site-wide nav chrome
    # (short, generic category labels like "Sundhed og sygdom") always sits
    # FIRST in DOM order, and the actually-useful, specific sub-topic links
    # only appear after it (position 26+ of 51 anchors on that page) --
    # capping at the first N in DOM order would show the model nothing but
    # the same nav chrome it's already reading in the page text, on every
    # page. Longer anchor text reliably means a more specific link (nav
    # items repeat the same handful of short category words site-wide;
    # content links describe one specific service), so sorting by text
    # length before capping surfaces the useful candidates instead.
    candidates.sort(key=lambda c: len(c["text"]), reverse=True)
    return candidates[:_MAX_LINK_CANDIDATES]


def _find_best_navigation_link(
    links: list[dict], raw_quote: str | None, question: dict, current_url: str
) -> str | None:
    """Programmatic navigation trigger (2026-08-20 debugging pass): if the
    model did not self-nominate a link, but the landing page is a category
    hub where the raw evidence quote matches a link label, or where sub-topic
    links strongly match the question's target keywords, automatically
    follow the most relevant deep link rather than stopping at the hub."""
    if not links:
        return None

    curr_parsed = urlparse(current_url)
    curr_path = curr_parsed.path.rstrip("/").lower()

    # 1. Match against raw quote (if assessor quoted a link label or nav item)
    if raw_quote:
        q_norm = raw_quote.strip().lower()
        if len(q_norm) >= 3:
            for l in links:
                l_text = l["text"].strip().lower()
                l_href = l["href"]
                l_path = urlparse(l_href).path.rstrip("/").lower()
                if l_path == curr_path:
                    continue
                if q_norm == l_text or q_norm in l_text or (len(l_text) >= 5 and l_text in q_norm):
                    return l_href

    # 2. Keyword relevance scoring against question title and text
    q_title = str(question.get("title") or "")
    q_text = str(question.get("text") or "")
    target_terms = set(re.findall(r"\w{3,}", (q_title + " " + q_text).lower()))

    stop_words = {
        "the", "and", "for", "with", "this", "that", "from", "main", "sectors",
        "evidence", "online", "services", "government", "portal", "website",
        "either", "page", "section", "six", "users", "ability", "information",
        "access", "national", "provision", "related", "different"
    }
    meaningful_terms = {t for t in target_terms if t not in stop_words}

    best_link = None
    best_score = 0
    for l in links:
        l_href = l["href"]
        l_path = urlparse(l_href).path.rstrip("/").lower()
        if l_path == curr_path:
            continue
        l_text = l["text"].lower()
        score = sum(2 for t in meaningful_terms if t in l_text)
        score += sum(1 for t in meaningful_terms if t in l_path)
        if score > best_score:
            best_score = score
            best_link = l_href

    if best_score >= 2 and best_link:
        return best_link

    return None


async def _evaluate_page(
    page_result,
    page,
    question: dict,
    profile: str,
    addendum: RetryAddendum | None,
    provider: ModelProvider,
    model: str,
    temperature: float,
    capture_dir: str,
    cost_ledger: CostLedger,
    agent_index: int,
    *,
    allow_navigation: bool,
) -> tuple[AssessorAgentOutput, str | None]:
    """One assess-and-parse pass against an already-fetched page. Returns
    the output plus a same-domain URL to follow next, or None if the model
    didn't nominate one (or `allow_navigation` is False, capping navigation
    to a single hop from `run_assessor_agent`)."""
    # search_by_text() (element_ref.py) only walks document.body when
    # relocating a quote, so any text pulled from <head> (the <title>
    # above all -- a common, reasonable thing for the model to quote)
    # is unlocatable no matter how the quote is worded. <script>/<style>
    # text is dropped too, both because it's never visible evidence and
    # because it would otherwise pad the prompt with raw code.
    body_soup = BeautifulSoup(page_result.html, "html.parser")
    for tag in body_soup(["script", "style", "head"]):
        tag.decompose()
    page_text = body_soup.get_text(" ", strip=True)

    links = await _extract_same_domain_links(page, page_result.final_url) if allow_navigation else []

    prompt = build_prompt(
        question_text=question["text"],
        answer_type=question["answer_type"],
        evidence_locus=question["evidence_locus"],
        page_text=page_text,
        profile=profile,
        addendum=addendum.model_dump() if addendum else None,
        available_links=links,
        title=question.get("title"),
        what=question.get("what"),
        why=question.get("why"),
        criteria_for_yes=question.get("criteria_for_yes"),
        criteria_for_no=question.get("criteria_for_no"),
        scoring_guidance=question.get("scoring_guidance"),
        benchmark_case=question.get("benchmark_case"),
    )

    response = await provider.generate(
        model=model,
        system_instruction="Respond with valid JSON matching the required schema only.",
        prompt=prompt,
        temperature=temperature,
        response_schema=_RESPONSE_SCHEMA,
    )
    cost_ledger.record(
        stage="assessor_run",
        model_identity=response.model_identity,
        input_units=response.input_tokens,
        output_units=response.output_tokens,
        cost=estimate_cost(response.model_identity, response.input_tokens, response.output_tokens),
        agent_index=agent_index,
    )

    parsed = _parse_model_json(response.text)

    evidence = None
    raw_quote = str(parsed.get("evidence_quote") or "").strip() or None
    evidence_located = None
    if raw_quote:
        located = await search_by_text(page, raw_quote)
        evidence_located = located is not None
        if located:
            ref = build_reference(located["css_path"], located["text"])
            capture_ref = await capture_region(page, located["css_path"], capture_dir)
            evidence = EvidenceOutput(
                resolved_url=page_result.final_url,
                capture_ref=capture_ref,
                element_reference=ElementReferenceOutput(**ref.__dict__),
                element_text=located["text"],
            )

    detected_language = str(parsed.get("detected_language") or "unknown").strip().lower() or "unknown"

    raw_answer = bool(parsed.get("answer", False)) if question["answer_type"] == "binary" else parsed.get("answer")
    raw_conf = max(0, min(100, int(parsed.get("confidence", 0))))

    # Hard confidence calibration for negative / anchor findings
    if not raw_answer and raw_conf > 60:
        raw_conf = 60

    output = AssessorAgentOutput(
        answer=raw_answer,
        confidence=raw_conf,
        justification=str(parsed.get("justification", "")),
        evidence=evidence,
        model_identity=response.model_identity,
        detected_language=detected_language,
        fill_gap_reason=str(parsed.get("fill_gap_reason") or "").strip() or None,
        link_likely_wrong=bool(parsed.get("link_likely_wrong", False)),
        raw_evidence_quote=raw_quote,
        evidence_located=evidence_located,
    )

    follow_url = None
    if allow_navigation and links:
        try:
            idx = int(parsed.get("follow_link_index", -1))
        except (TypeError, ValueError):
            idx = -1
        if 0 <= idx < len(links):
            follow_url = links[idx]["href"]

        # Programmatic trigger: if model did not pick a link, but answered False or low confidence
        if not follow_url and (not output.answer or output.confidence < 70):
            auto_url = _find_best_navigation_link(links, raw_quote, question, page_result.final_url)
            if auto_url:
                follow_url = auto_url

    return output, follow_url


def _parse_model_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "answer": False,
            "confidence": 0,
            "justification": "Model output was not valid JSON.",
            "evidence_quote": "",
            "detected_language": "unknown",
            "fill_gap_reason": "model returned malformed JSON, could not be parsed",
            "link_likely_wrong": False,
            "follow_link_index": -1,
        }


class AssessorAgent(BaseAgent[AssessorAgentInput, AssessorAgentRun]):
    """Assessor Agent implementation."""

    def __init__(self, provider: ModelProvider = None, browser: BrowserSession = None, name: str = "AssessorAgent", description: str = ""):
        super().__init__(name=name, description=description or "Evaluates questions against target portals.")
        self.provider = provider
        self.browser = browser

    async def run(self, input_data: AssessorAgentInput, **kwargs) -> AssessorAgentRun:
        """Executes the assessor agent logic."""
        settings = kwargs["settings"]
        fetch_log = kwargs["fetch_log"]
        stage_log = kwargs["stage_log"]
        cost_ledger = kwargs["cost_ledger"]
        capture_dir = kwargs["capture_dir"]

        return await run_assessor_agent(
            session_id=input_data.session_id,
            question=input_data.question.model_dump(),
            portal_url=input_data.portal.resolved_url,
            agent_index=input_data.agent_index,
            round_number=input_data.round_number,
            settings=settings,
            provider=self.provider,
            browser=self.browser,
            fetch_log=fetch_log,
            stage_log=stage_log,
            cost_ledger=cost_ledger,
            capture_dir=capture_dir,
            addendum=input_data.addendum,
            portal_id=input_data.portal.portal_id,
        )

