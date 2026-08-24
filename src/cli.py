"""EKAP AIQ command-line interface.

Subcommands are added incrementally as each pipeline stage is implemented;
see specs/001-ekap-aiq-assessment/quickstart.md for the full command set
this mirrors.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace

import click

from shared.config.settings import Settings, load_settings
from shared.config.validation import ConfigurationError, validate_settings
from shared.persistence.schema import connect, init_db


def _connect(settings: Settings) -> sqlite3.Connection:
    return connect(settings.database_path)


@click.group()
@click.option("--env-file", default=".env", help="Path to .env file")
@click.pass_context
def main(ctx: click.Context, env_file: str) -> None:
    """EKAP AIQ — AI-assisted portal assessment proof of concept."""
    ctx.ensure_object(dict)
    ctx.obj["env_file"] = env_file
    ctx.obj["settings"] = load_settings(env_file)


@main.group()
def config() -> None:
    """Inspect configuration."""


@config.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Print every parameter with its effective value, default, and source (FR-073)."""
    settings: Settings = ctx.obj["settings"]
    defaults = Settings.defaults().as_dict()
    effective = settings.as_dict()

    click.echo(f"{'PARAMETER':<42} {'EFFECTIVE':<30} {'DEFAULT':<30} SOURCE")
    for key in sorted(effective):
        eff = effective[key]
        default = defaults[key]
        source = "default" if eff == default else "configured"
        click.echo(f"{key:<42} {str(eff):<30} {str(default):<30} {source}")

    try:
        validate_settings(settings)
        click.secho("\nConfiguration is valid.", fg="green")
    except ConfigurationError as exc:
        click.secho(f"\n{exc}", fg="red")


@main.group()
def db() -> None:
    """Database administration."""


@db.command("init")
@click.pass_context
def db_init(ctx: click.Context) -> None:
    """Create the append-only schema (FR-062)."""
    settings: Settings = ctx.obj["settings"]
    init_db(settings.database_path)
    click.secho(f"Initialized database at {settings.database_path}", fg="green")


@main.group()
def seed() -> None:
    """Seed demo / fixture data."""


@seed.command("demo-review")
@click.pass_context
def seed_demo_review_cmd(ctx: click.Context) -> None:
    """Seed one complete assessment and one with broken evidence, for
    demonstrating the review surface with no assessment pipeline running
    (US1 independent test)."""
    settings: Settings = ctx.obj["settings"]
    from shared.persistence.schema import init_db
    from review.seed_demo import seed_demo_review

    init_db(settings.database_path)
    conn = _connect(settings)
    result = seed_demo_review(conn)
    click.secho(f"Seeded session={result['session_id']} portal={result['portal_id']}", fg="green")
    click.echo(f"Open: http://{settings.serve_host}:{settings.serve_port}/?session={result['session_id']}")


@seed.command("demo")
@click.pass_context
def seed_demo_cmd(ctx: click.Context) -> None:
    """Seed the platform demo: two real projects (UN E-Gov 2026, LOSI UK 2025),
    live AI pre-fill against real government portals, the real Denmark MSQ
    ingested, and a deliberately-flagged Assessor A/B discrepancy so the
    arbitration queue has a real case to show."""
    settings: Settings = ctx.obj["settings"]
    from shared.persistence.repositories import Repository
    from portal.seed import seed_demo_data

    init_db(settings.database_path)
    conn = _connect(settings)
    repo = Repository(conn)
    result = run_async(seed_demo_data(repo, settings))
    click.secho(f"Seeded projects: {', '.join(result['cycles'])}", fg="green")
    click.echo(f"Open: http://{settings.serve_host}:{settings.serve_port}/")


@seed.command("ekap-demo")
@click.pass_context
def seed_ekap_demo_cmd(ctx: click.Context) -> None:
    """Alias for 'aiq seed demo'."""
    ctx.forward(seed_demo_cmd)


@main.command()
@click.pass_context
def serve(ctx: click.Context) -> None:
    """Start the app: Admin, Assessor Portal, AI Review (mounted at
    /review), and the Public Knowledge Base (spec 005)."""
    settings: Settings = ctx.obj["settings"]
    import uvicorn

    from portal.webapp import build_app

    init_db(settings.database_path)
    app = build_app(settings.database_path, settings)
    uvicorn.run(app, host=settings.serve_host, port=settings.serve_port)


@main.group()
def audit() -> None:
    """Audit trail reconstruction (FR-061)."""


@audit.command("reconstruct")
@click.option("--session", "session_id", required=True)
@click.option("--question", "question_id", default=None)
@click.option("--portal", "portal_id", default=None)
@click.pass_context
def audit_reconstruct(ctx: click.Context, session_id: str, question_id: str | None, portal_id: str | None) -> None:
    """Reconstruct full history from the session identifier alone (SC-005)."""
    settings: Settings = ctx.obj["settings"]
    from shared.persistence.repositories import Repository
    from review.audit import reconstruct_question_history, reconstruct_session_summary

    conn = _connect(settings)
    repo = Repository(conn)
    if question_id and portal_id:
        result = reconstruct_question_history(repo, session_id, question_id, portal_id)
    else:
        result = reconstruct_session_summary(repo, session_id)
    click.echo(json.dumps(result, indent=2, default=str))


@main.group()
def verify() -> None:
    """Post-hoc verification of pipeline invariants (FR-112–FR-118)."""


@verify.command("independence")
@click.option("--session", "session_id", required=True)
@click.pass_context
def verify_independence_cmd(ctx: click.Context, session_id: str) -> None:
    """SC-008, SC-017: no agent's input contained another agent's output;
    the population of results shows a non-degenerate spread."""
    settings: Settings = ctx.obj["settings"]
    from agents.verify import verify_independence
    from shared.persistence.repositories import Repository

    repo = Repository(_connect(settings))
    report = verify_independence(repo, session_id)

    click.echo(f"Total runs: {report.total_runs} across {report.total_units} units")
    if report.cross_contamination_findings:
        click.secho("Cross-contamination findings:", fg="red")
        for f in report.cross_contamination_findings:
            click.echo(f"  - {f}")
    if report.degenerate_units:
        click.secho(f"Degenerate (zero-variance) units: {len(report.degenerate_units)}", fg="yellow")
        for u in report.degenerate_units:
            click.echo(f"  - {u}")
    if report.clean:
        click.secho("Independence checks passed.", fg="green")
    else:
        click.secho("Independence checks FAILED.", fg="red")
        raise SystemExit(1)


@verify.command("evidence")
@click.option("--session", "session_id", required=True)
@click.pass_context
def verify_evidence_cmd(ctx: click.Context, session_id: str) -> None:
    """SC-018: 100% of answers reaching adjudication carry independently
    verified evidence with a verification timestamp."""
    settings: Settings = ctx.obj["settings"]
    from agents.verify import verify_evidence_reached_adjudication
    from shared.persistence.repositories import Repository

    repo = Repository(_connect(settings))
    report = verify_evidence_reached_adjudication(repo, session_id)

    click.echo(
        f"{report.total_validated_pass_runs - report.unverified_count}/"
        f"{report.total_validated_pass_runs} validated-pass runs carry verified evidence"
    )
    if report.clean:
        click.secho("Evidence verification checks passed.", fg="green")
    else:
        click.secho(f"{report.unverified_count} run(s) reached validated_pass without verified evidence:", fg="red")
        for rid in report.unverified_run_ids:
            click.echo(f"  - {rid}")
        raise SystemExit(1)


@main.command()
@click.option("--cycle", "cycle_id", required=True, help="Survey cycle id to run against")
@click.option("--portal", "portal_filter", default=None, help="Restrict to one country id")
@click.option("--questions", "questions_filter", default=None, help="Comma-separated question ids")
@click.option("--agents", "agents_override", type=int, default=None, help="Override AIQ_ASSESSOR_AGENT_COUNT")
@click.option("--batch-size", "batch_size_override", type=int, default=None, help="Override AIQ_BATCH_SIZE")
@click.option("--no-adjudicate", is_flag=True, default=False, help="Stop after assessment; skip adjudication")
@click.option("--resume", is_flag=True, default=False, help="Resume the most recent non-complete session for this cycle")
@click.option("--session", "session_id_opt", default=None, help="Resume a specific session id instead of the latest")
@click.pass_context
def run(
    ctx: click.Context, cycle_id: str, portal_filter: str | None, questions_filter: str | None,
    agents_override: int | None, batch_size_override: int | None, no_adjudicate: bool,
    resume: bool, session_id_opt: str | None,
) -> None:
    """Run (or resume) an AI prefill assessment batch for one survey cycle (spec 008 decoupled prefill)."""
    settings: Settings = ctx.obj["settings"]

    if agents_override is not None:
        settings.assessor_agent_count = agents_override
        settings.agent_models = (settings.agent_models * agents_override)[:agents_override] or settings.agent_models
        settings.agent_temperatures = (settings.agent_temperatures * agents_override)[:agents_override]
        settings.agent_prompt_profiles = (settings.agent_prompt_profiles * agents_override)[:agents_override]
    if batch_size_override is not None:
        settings.batch_size = batch_size_override

    try:
        validate_settings(settings)
    except ConfigurationError as exc:
        click.secho(str(exc), fg="red")
        raise SystemExit(1)

    init_db(settings.database_path)
    conn = _connect(settings)

    from core.llm_factory import ModelProvider
    from orchestration.scheduler import run_batch
    from portal.common import ensure_session
    from shared.persistence.repositories import Repository
    from shared.tools.browser import BrowserSession
    from shared.ratelimit.token_bucket import RateLimiter
    from core.telemetry.cost_ledger import CostLedger
    from core.telemetry.fetch_log import FetchLog
    from core.telemetry.stage_events import StageEventLog

    repo = Repository(conn)

    if session_id_opt:
        # An explicit --session always wins, resume or not (e.g. targeting an
        # ad-hoc benchmark session rather than the cycle's canonical one).
        session_id = session_id_opt
        click.echo(f"{'Resuming' if resume else 'Using'} session {session_id}")
    elif resume:
        row = conn.execute(
            "SELECT session_id FROM assessment_sessions WHERE cycle_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (cycle_id,),
        ).fetchone()
        if not row:
            click.secho(f"No session found to resume for cycle {cycle_id!r}.", fg="red")
            raise SystemExit(1)
        session_id = row["session_id"]
        click.echo(f"Resuming session {session_id}")
    else:
        # One long-lived session per cycle (portal.common.session_id_for_cycle):
        # every AI pre-fill run and every human A/B submission for a cycle
        # accumulates into it, so the portal can see what this CLI produces.
        session_id = ensure_session(repo, cycle_id)
        click.echo(f"Using session {session_id}")

    questions = repo.list_questions(cycle_id)
    if questions_filter:
        wanted = set(questions_filter.split(","))
        questions = [q for q in questions if q.question_id in wanted]
    portals = repo.list_portals(cycle_id)
    if portal_filter:
        portals = [p for p in portals if p.country_id == portal_filter]

    if not questions or not portals:
        click.secho(
            f"No questions/portals to run: {len(questions)} question(s), {len(portals)} portal(s) "
            f"for cycle {cycle_id!r}. Seed the cycle's questions and target portals first.",
            fg="yellow",
        )
        return

    async def _run() -> None:
        limiter = RateLimiter(rate_per_sec=settings.rate_limit_per_domain_rps)
        provider = ModelProvider(
            settings.google_cloud_project,
            settings.google_cloud_location,
            settings.google_genai_use_vertexai,
            settings.google_api_key,
        )
        browser = BrowserSession(settings.user_agent, limiter)
        await browser.start()

        import httpx

        try:
            async with httpx.AsyncClient(timeout=15.0) as http_client:
                summary = await run_batch(
                    repo=repo, settings=settings, session_id=session_id, provider=provider,
                    browser=browser, http_client=http_client,
                    fetch_log=FetchLog(conn, session_id), stage_log=StageEventLog(conn, session_id),
                    cost_ledger=CostLedger(conn, session_id),
                    questions=questions, portals=portals, adjudicate_results=not no_adjudicate,
                )
        finally:
            await browser.stop()

        click.echo(
            f"suggested={summary.delivered} no_suggestion={summary.no_suggestion + summary.unassessable} "
            f"(delivered={summary.delivered} escalated={summary.escalated} "
            f"unassessable={summary.unassessable} in_progress={summary.in_progress} "
            f"of {len(summary.outcomes)} units)"
        )

    run_async(_run())


@verify.command("resume")
@click.option("--session", "session_id", required=True)
@click.pass_context
def verify_resume_cmd(ctx: click.Context, session_id: str) -> None:
    """SC-006: zero duplicated and zero lost units after a resume."""
    settings: Settings = ctx.obj["settings"]
    from shared.persistence.repositories import Repository
    from orchestration.verify import verify_resume

    repo = Repository(_connect(settings))
    report = verify_resume(repo, session_id, settings.assessor_agent_count)

    click.echo(f"Checked {report.total_units} unit(s).")
    if report.duplicated_units:
        click.secho("Duplicated units:", fg="red")
        for u in report.duplicated_units:
            click.echo(f"  - {u}")
    if report.lost_units:
        click.secho("Lost units (delivered without sufficient validated evidence):", fg="red")
        for u in report.lost_units:
            click.echo(f"  - {u}")
    if report.clean:
        click.secho("Resume checks passed: zero duplicated, zero lost.", fg="green")
    else:
        click.secho("Resume checks FAILED.", fg="red")
        raise SystemExit(1)


@main.group()
def question() -> None:
    """Manage questionnaire and questions."""


@question.command("add")
@click.option("--question-id", required=True, help="Question identifier, e.g. OSQ-CUSTOM-01")
@click.option("--text", required=True, help="Question text")
@click.option("--author", "author_actor_id", required=True, help="Author/actor ID")
@click.option("--cycle", "cycle_id", required=True, help="Survey cycle ID")
@click.option("--answer-type", type=click.Choice(["binary", "scalar", "enum"]), default="binary")
@click.option("--evidence-locus", type=click.Choice(["national_portal_only", "any_government_domain"]), default="national_portal_only")
@click.option("--requires-auth", is_flag=True, default=False)
@click.option("--session", "session_id", default=None, help="Optional session ID to enqueue mid-run")
@click.pass_context
def question_add_cmd(
    ctx: click.Context, question_id: str, text: str, author_actor_id: str,
    cycle_id: str, answer_type: str, evidence_locus: str, requires_auth: bool, session_id: str | None,
) -> None:
    """Add a custom, cycle-scoped question (FR-053, FR-054)."""
    settings: Settings = ctx.obj["settings"]
    from shared.state.entities import AnswerType, EvidenceLocus, Question
    from shared.persistence.repositories import Repository

    init_db(settings.database_path)
    conn = _connect(settings)
    repo = Repository(conn)

    q = Question(
        question_id=question_id,
        cycle_id=cycle_id,
        text=text,
        answer_type=AnswerType(answer_type),
        evidence_locus=EvidenceLocus(evidence_locus),
        is_custom=True,
        author_actor_id=author_actor_id,
        requires_authenticated_access=requires_auth,
    )
    repo.insert_question(q)
    click.secho(f"Added custom question {question_id} (cycle={cycle_id}, author={author_actor_id})", fg="green")

    if session_id:
        from orchestration.scheduler import enqueue_custom_question
        portals = repo.list_portals(cycle_id)
        enqueued = enqueue_custom_question(repo, session_id, q, portals)
        click.echo(f"Enqueued {len(enqueued)} units mid-run for session {session_id}.")


@question.command("edit")
@click.option("--question-id", required=True, help="Existing custom question identifier")
@click.option("--text", required=True, help="Revised question text")
@click.option("--editor", "revised_by", required=True, help="Actor ID making the edit")
@click.pass_context
def question_edit_cmd(ctx: click.Context, question_id: str, text: str, revised_by: str) -> None:
    """Edit an existing custom question (default questionnaire questions are immutable)."""
    settings: Settings = ctx.obj["settings"]
    from shared.persistence.repositories import Repository

    init_db(settings.database_path)
    conn = _connect(settings)
    repo = Repository(conn)

    existing = repo.get_question(question_id)
    if existing is None:
        click.secho(f"No such question: {question_id}", fg="red")
        raise SystemExit(1)

    updated = replace(existing, text=text)
    try:
        repo.update_question(updated, revised_by=revised_by)
    except ValueError as exc:
        click.secho(str(exc), fg="red")
        raise SystemExit(1)

    revision_count = repo.count_question_revisions(question_id)
    click.secho(
        f"Edited {question_id} (revision #{revision_count}, editor={revised_by})", fg="green"
    )


@main.group()
def benchmark() -> None:
    """Benchmark evaluation mode and cross-run comparison."""


@benchmark.command("run")
@click.option("--set", "set_id", required=True, help="Benchmark set ID")
@click.option("--dataset", "json_dataset", default="data/benchmark/module_2_1.json", help="Path to JSON dataset")
@click.pass_context
def benchmark_run_cmd(ctx: click.Context, set_id: str, json_dataset: str) -> None:
    """Run pipeline in benchmark mode against ground truth dataset (FR-093)."""
    settings: Settings = ctx.obj["settings"]
    from benchmark.runner import run_benchmark_session
    from benchmark.store import BenchmarkStore
    from shared.persistence.repositories import Repository

    init_db(settings.database_path)
    conn = _connect(settings)
    repo = Repository(conn)
    store = BenchmarkStore(conn)

    b_set = store.load_from_json(json_dataset, set_id, "Benchmark Set")
    gt_list = store.list_ground_truth(set_id)

    questions = repo.list_questions("2026-cycle") or []
    portals = repo.list_portals("2026-cycle") or []

    async def _run():
        session_id, result = await run_benchmark_session(repo, settings, set_id, questions, portals)
        click.secho(f"Completed benchmark session {session_id}", fg="green")
        click.echo(f"Overall Accuracy: {result.overall_accuracy:.2%}")
        click.echo(f"Discrepancy Flag Rate: {result.discrepancy_flag_rate:.2%}")

    run_async(_run())


@benchmark.command("compare")
@click.option("--run", "session_id_a", required=True, help="Session A ID")
@click.option("--against", "session_id_b", required=True, help="Session B ID")
@click.pass_context
def benchmark_compare_cmd(ctx: click.Context, session_id_a: str, session_id_b: str) -> None:
    """Compare two benchmark runs (FR-099, SC-022)."""
    settings: Settings = ctx.obj["settings"]
    from benchmark.compare import compare_benchmark_runs
    from shared.persistence.repositories import Repository

    conn = _connect(settings)
    repo = Repository(conn)
    report = compare_benchmark_runs(repo, session_id_a, session_id_b)
    click.echo(json.dumps(asdict(report), indent=2, default=str))


@main.command()
@click.option("--cycle", "cycle_id", required=True, help="Survey cycle ID to export")
@click.option("--out", "output_dir", default="./data/exports", help="Output directory")
@click.option("--actor", "actor_id", default="system-exporter", help="Producing actor ID")
@click.pass_context
def export(ctx: click.Context, cycle_id: str, output_dir: str, actor_id: str) -> None:
    """Export delivered answers and exclusion report for a cycle (FR-101–FR-106)."""
    settings: Settings = ctx.obj["settings"]
    from export.writer import export_cycle_answers
    from shared.persistence.repositories import Repository

    conn = _connect(settings)
    repo = Repository(conn)
    ndjson_path, excl_path = export_cycle_answers(repo, cycle_id, output_dir, actor_id)
    click.secho(f"Exported NDJSON to {ndjson_path}", fg="green")
    click.secho(f"Exported Exclusion Report to {excl_path}", fg="green")


@main.group()
def telemetry() -> None:
    """Inspect telemetry, fetch counts, timings, and model cost."""


@telemetry.command("summary")
@click.option("--session", "session_id", required=True)
@click.pass_context
def telemetry_summary_cmd(ctx: click.Context, session_id: str) -> None:
    """Print telemetry summary report (FR-112)."""
    settings: Settings = ctx.obj["settings"]
    from core.telemetry.reports import get_telemetry_summary

    conn = _connect(settings)
    res = get_telemetry_summary(conn, session_id)
    click.echo(json.dumps(res, indent=2, default=str))


@telemetry.command("timings")
@click.option("--session", "session_id", required=True)
@click.pass_context
def telemetry_timings_cmd(ctx: click.Context, session_id: str) -> None:
    """Print stage execution timings (FR-113, FR-114)."""
    settings: Settings = ctx.obj["settings"]
    from core.telemetry.reports import get_timings_report

    conn = _connect(settings)
    res = get_timings_report(conn, session_id)
    click.echo(json.dumps(res, indent=2, default=str))


@telemetry.command("fetches")
@click.option("--session", "session_id", required=True)
@click.pass_context
def telemetry_fetches_cmd(ctx: click.Context, session_id: str) -> None:
    """Print per-domain fetch counts (assessor vs validator) (FR-115)."""
    settings: Settings = ctx.obj["settings"]
    from core.telemetry.reports import get_fetches_report

    conn = _connect(settings)
    res = get_fetches_report(conn, session_id)
    click.echo(json.dumps(res, indent=2, default=str))


@telemetry.command("cost")
@click.option("--session", "session_id", required=True)
@click.pass_context
def telemetry_cost_cmd(ctx: click.Context, session_id: str) -> None:
    """Print model invocation cost ledger (FR-116)."""
    settings: Settings = ctx.obj["settings"]
    from core.telemetry.reports import get_cost_report

    conn = _connect(settings)
    res = get_cost_report(conn, session_id)
    click.echo(json.dumps(res, indent=2, default=str))


@verify.command("benchmark-isolation")
@click.option("--session", "session_id", required=True)
@click.pass_context
def verify_benchmark_isolation_cmd(ctx: click.Context, session_id: str) -> None:
    """Assert ground truth reached zero agent/validator/adjudicator invocations (FR-094, SC-021)."""
    settings: Settings = ctx.obj["settings"]
    from benchmark.verify import verify_benchmark_isolation
    from shared.persistence.repositories import Repository

    conn = _connect(settings)
    repo = Repository(conn)
    report = verify_benchmark_isolation(repo, session_id)
    if report.clean:
        click.secho("Benchmark isolation checks passed: zero ground-truth leakage.", fg="green")
    else:
        click.secho("Benchmark isolation checks FAILED.", fg="red")
        for f in report.leakage_findings:
            click.echo(f"  - {f}")
        raise SystemExit(1)


@verify.command("telemetry-hygiene")
@click.option("--session", "session_id", required=True)
@click.pass_context
def verify_telemetry_hygiene_cmd(ctx: click.Context, session_id: str) -> None:
    """Assert zero credentials and zero ground truth in telemetry (FR-110, FR-117)."""
    settings: Settings = ctx.obj["settings"]
    from telemetry.verify import verify_telemetry_hygiene

    conn = _connect(settings)
    report = verify_telemetry_hygiene(conn, session_id)
    if report.clean:
        click.secho("Telemetry hygiene checks passed: zero credentials, zero ground truth.", fg="green")
    else:
        click.secho("Telemetry hygiene checks FAILED.", fg="red")
        for f in report.findings:
            click.echo(f"  - {f}")
        raise SystemExit(1)


@verify.command("no-credentials")
@click.pass_context
def verify_no_credentials_cmd(ctx: click.Context) -> None:
    """Assert zero credentials across all database/observability records (FR-110)."""
    settings: Settings = ctx.obj["settings"]
    from telemetry.verify import verify_no_credentials

    conn = _connect(settings)
    report = verify_no_credentials(conn)
    if report.clean:
        click.secho("No-credentials check passed across all tables.", fg="green")
    else:
        click.secho("No-credentials check FAILED.", fg="red")
        for f in report.findings:
            click.echo(f"  - {f}")
        raise SystemExit(1)


@main.group()
def diagnose() -> None:
    """Link resolution diagnostics and regression checks (spec 009)."""


@diagnose.command("run")
@click.option("--cycle", "cycle_id", default="usa-test-2026", help="Survey cycle id under test")
@click.option("--questions", "questions_filter", default=None, help="Comma-separated question or indicator IDs")
@click.option("--reference-set", "reference_set_id", default="bm-reference-links-us", help="Benchmark reference set ID")
@click.option("--fixture", "fixture_path", default="data/benchmark/reference_links_us.json", help="Reference links fixture path")
@click.option("--resolve-only", is_flag=True, default=False, help="Stop after link resolution; skip assessor model calls")
@click.option("--check-staleness", is_flag=True, default=False, help="Verify reference URLs are still live")
@click.pass_context
def diagnose_run_cmd(
    ctx: click.Context,
    cycle_id: str,
    questions_filter: str | None,
    reference_set_id: str,
    fixture_path: str,
    resolve_only: bool,
    check_staleness: bool,
) -> None:
    """Run link resolution diagnostics over reference set and output report."""
    import asyncio
    from shared.persistence.repositories import Repository
    from benchmark.diagnostics import run_diagnostic
    from benchmark.report import render_diagnostic_report

    settings: Settings = ctx.obj["settings"]
    conn = _connect(settings)
    repo = Repository(conn)

    q_filter = [q.strip() for q in questions_filter.split(",") if q.strip()] if questions_filter else None

    result = asyncio.run(
        run_diagnostic(
            repo=repo,
            settings=settings,
            benchmark_set_id=reference_set_id,
            cycle_id=cycle_id,
            reference_fixture_path=fixture_path,
            question_filter=q_filter,
            resolve_only=resolve_only,
            check_staleness=check_staleness,
        )
    )

    report_text = render_diagnostic_report(result)
    click.echo(report_text)


@diagnose.command("compare")
@click.argument("session_a")
@click.argument("session_b")
@click.option("--fail-on-regression", is_flag=True, default=False, help="Exit non-zero if any indicator regressed")
@click.pass_context
def diagnose_compare_cmd(
    ctx: click.Context,
    session_a: str,
    session_b: str,
    fail_on_regression: bool,
) -> None:
    """Compare two diagnostic runs and surface regressions."""
    from shared.persistence.repositories import Repository
    from benchmark.compare import compare_diagnostic_runs

    settings: Settings = ctx.obj["settings"]
    conn = _connect(settings)
    repo = Repository(conn)

    report = compare_diagnostic_runs(repo, session_a, session_b)
    click.echo(report.summary)

    if fail_on_regression and report.has_regression:
        click.secho("Regression detected in link resolution diagnostics!", fg="red", err=True)
        raise SystemExit(1)


def run_async(coro):
    return asyncio.run(coro)


if __name__ == "__main__":
    main()

