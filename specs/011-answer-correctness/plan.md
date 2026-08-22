# 011 — Get to a Meaningful Answer, Simply

**Goal: one straight path that lands on the right page and delivers a defensible answer.
Nothing else, until that number is good.**

---

## Where we actually are

Session `bm-sess-4cbbf16a72e3`, 25 US questions, 2026-08-21:

| | |
|---|---|
| Delivered | 20 |
| Withheld (`insufficient_positions`) | 5 |
| **Delivered and correct** | **12 of 25 (48%)** — 12 of 20 delivered (60%) |

Every miss is **False when the truth is True**, or withheld. Zero false positives.
The pipeline is not guessing wrong; it fails to find, then honestly reports "not found".

> **Reconcile first (T001).** `scripts/score_25q.py` reported *14* of 25 via the diagnostic's
> `answer_verdict`, which also credits link-resolution alternatives. The delivered-prefill count is
> *12*. Two different things are being called "correct". Pick the delivered-prefill count — it is
> what a human reviewer actually receives — and make the script print only that.

---

## Finding 1 — the domain lock and the ground truth contradict each other

Cross-tabulating each question's `evidence_locus` tag against its ground-truth reference URL:

| Question | Tagged | Truth lives on | Landed on |
|---|---|---|---|
| EP-304 | `national_portal_only` | usaspending.gov | www.usa.gov |
| IF-337 | `national_portal_only` | cio.gov | www.usa.gov |
| IF-338 | `national_portal_only` | justice.gov | www.usa.gov |
| SP-166 | `national_portal_only` | epa.gov | www.usa.gov |
| TECH-022 | `national_portal_only` | login.gov | www.usa.gov |
| IF-011 | `national_portal_only` | whitehouse.gov | www.usa.gov |
| …5 more | `national_portal_only` | *not* usa.gov | — |

**11 of 25 questions are tagged "the answer must be on the national portal" while their own ground
truth says it is on an agency site.** The pipeline obeyed, searched only usa.gov, correctly found
nothing, answered False. **18 of 25 units resolved to `www.usa.gov`.**

The lock is not even locus-driven — `scheduler.py:~330` restricts **every** question on attempt #1:

```python
is_first_attempt = unit_data.get("link_retry_count", 0) == 0
restrict_to_portal = is_first_attempt      # -> restrict_domain = "www.usa.gov"
```

## Finding 2 — but the restricted source is the *best* source

This is the finding that killed the obvious fix. Correctness by supplying source:

| Source | Correct | |
|---|---|---|
| **sitemap** | **7/11 (63%)** | portal deep links — *only runs when the domain lock is on* |
| search | 5/12 (41%) | |
| portal_default | 0/2 | homepage fallback |
| `prior_survey_kb`, `msq` | supplied 0 of 25 | 26 attempts each, tables empty |

**Simply removing the domain lock would disable the highest-accuracy source and probably lower the
score.** The first draft of this plan proposed exactly that. It was wrong.

### What the two findings mean together

Sitemap is excellent *when the answer is on the portal* and fatal *when it isn't* — and nothing in
the pipeline decides which case it is in. `chain.py:~130` runs sitemap first whenever a restriction
is set, sitemap matches **lexically** against 1,531 URLs, and any weak lexical hit wins before web
search is ever consulted. The chain does have an off-portal escalation, but it only fires when the
portal yields *nothing* — a shallow generic page counts as something.

*The bug is not the domain lock and not the sitemap. It is that precedence is decided by
ordering rather than by judgment.*

---

## What "simplify" means here

010 deleted ~750 lines and the number did not move — it was never measured, and the deleted code
was not what blocked answers.

> **Simplification = fewer arbitrary rules deciding the outcome. Not: fewer files.**

The live path with `AIQ_ASSESSOR_AGENT_COUNT=1` is four stages, all earning their place:

```
resolve_link  →  assessor ×1  →  confidence gate  →  validator (+2 retries)  →  prefill
```

### Dormant, not dead — leave it, stop reasoning about it

Verified zero call sites on the live path:

| Component | Status |
|---|---|
| `AdjudicatorAgent` / `adjudicator_node` | re-exported in `agents/__init__.py` only |
| `run_adjudication_retry_loop` | **zero** call sites anywhere |
| `PortalAdjudicatorAgent` | re-exported only |
| `ResolverAgent` | reachable only when 2 agents disagree — impossible at `agent_count=1` |

- [ ] T002 Add one comment block atop `src/orchestration/scheduler.py` naming the live path and listing the above as dormant-pending-`agent_count=2`. **Do not delete** — this is the 2-agent configuration, not waste.

`prior_survey_kb` and `msq` return nothing, but are ~20-line local SQLite lookups with no network
cost, and production populates exactly those tables. Empty ≠ over-engineered. **No change.**

---

## Step 0 — Clean slate ✅ done

- [x] T003 Wrote `scripts/reset_runs.py`: deletes every run-scoped row (sessions, units, agent runs, validations, prefills, evidence, telemetry) while preserving seed rows (cycle, questions, portal, benchmark set, ground truth). Deleting the `.db` outright — what the old `clean_usa_runs.py` did — would also destroy the 25 questions and 31 ground-truth rows and force a re-seed.
- [x] T004 Backed up the baseline DB to `data/usa_sample.baseline-bm-sess-4cbbf16a72e3.db.bak`, then purged **1,161 rows across 11 tables**. Preserved: 25 questions, 31 ground-truth, 1 portal, 1 cycle.

*Why this matters beyond tidiness: `process_unit` short-circuits on a unit already in a terminal
state. Leftover units make a fresh run silently skip work and report stale numbers.*

---

## Step 1 — Let judgment decide the landing page, not ordering

The mechanism already exists and is already paid for: `relevance.choose_best()` is an LLM judge that
picks the most relevant candidate. Today it only ever sees **one source's** candidates, because the
chain returns on the first source that yields anything.

### Interface facts the implementer needs first (verified 2026-08-21)

These constrain the design, and getting them wrong wastes a full pass:

- `resolve_from_sitemap()` (`sources/sitemap.py:186`) returns a **`ResolutionAttempt`** — one
  already-chosen URL, not a candidate list. Its internal ranking is **lexical**.
- `search_for_link()` (`sources/search.py:326`) also returns a **`ResolutionAttempt`**. It calls
  `choose_best()` internally (`search.py:415`) over *its own* candidates, then collapses the winner
  to a single attempt via `_hit()` (`search.py:475`).
- **Neither source exposes its candidate list.** A naive "merge the candidates" refactor requires
  changing the return type of both sources and every caller — do not start there.
- `choose_best()` (`relevance.py:14`) takes any list of `{url, title, snippet}`-ish items and
  returns an index or `None`. It is reusable as-is at chain level.

**Decision — adjudicate at chain level over the two winners, not over merged candidates.**
Each source keeps its current signature and picks its own best. `chain.py` then asks `choose_best()`
once more over the ≤2 surviving URLs. Cost: one extra judge call per unit, zero interface churn.
Known limitation, accepted for now: a strong agency page ranked #3 *inside* search never surfaces,
because search already collapsed to its own #1. Revisit only if T016 shows search picks are the
weak link.

- [ ] T005 In `src/shared/tools/linkresolution/chain.py` (~L130, the `source_name == "search"` branch), stop returning on the sitemap's first usable hit. Run the sitemap attempt **and** the search attempt, keeping both `ResolutionAttempt`s. Search must run **unrestricted** here even when the sitemap was portal-scoped (see T007).
- [ ] T006 Adjudicate the two winners with `choose_best()` at chain level, passing `{"url": attempt.returned, "title": <question title>, "snippet": ""}` for each. **Portal is the tie-break, not the default**: if `choose_best` returns `None`, prefer the sitemap/portal attempt. This preserves sitemap's 63% on genuinely-portal questions while letting an agency page win when it is plainly better. Record which source won on `ResolutionAttempt`/`resolution_history` so T016 can measure it.
- [ ] T007 Split the conflated flag. `restrict_domain` currently scopes **both** the sitemap and the search filter (`search.py:392`, `_query_variants` at `search.py:308` adds `site:`). The sitemap must stay portal-scoped — that is what makes it a sitemap — but search must not be `site:`-locked on attempt #1. Pass the portal scope to the sitemap only; pass `restrict_domain=None` to `search_for_link`.
- [ ] T008 Cost check **before** running the gate: attempt #1 now does a sitemap pass **and** a search pass **and** one extra judge call per unit, where today most units short-circuit after the sitemap. Estimate ≈ +1 search + 1 cheap LLM call × 25 units. Confirm acceptable; if not, gate the search pass on the sitemap's lexical score being weak rather than running it unconditionally.

### Tests (write before T005 — house rule is tests-first)

- [ ] T009 Unit test in `tests/unit/`: given a sitemap attempt and a search attempt both usable, `choose_best` returning index 1 selects the **search** URL; returning `None` selects the **sitemap** URL (tie-break). Use a fake provider — no network.
- [ ] T010 Unit test: when the sitemap yields nothing usable, the search attempt is returned unchanged and no judge call is made (single-candidate short-circuit).
- [ ] T011 Regression test: `search_for_link` is invoked with `restrict_domain=None` on attempt #1 while the sitemap still receives the portal URL. This is the exact bug T007 fixes — assert it at the call boundary, since it is invisible in the output.
- [ ] T012 Run the full suite (`pytest -q`). Baseline is **281 passed**; any drop is a regression to fix before the gate, not after.

**Retired ideas, recorded so they are not re-proposed:**
- ~~Drop the domain lock entirely~~ — Finding 2: disables the best source.
- ~~Re-resolve after a negative answer~~ — a second full pass to undo a bad first attempt; making attempt #1 correct is simpler and cheaper.
- ~~Re-tag the 11 contradictory fixture rows~~ — bigger and more debatable than fixing precedence; revisit only if T017 shows it is still needed.

## Step 2 — Unblock the 5 withheld (2 lines of config)

Validator quality is `checks_passed / 3.0` → only ever `0.333`, `0.667`, `1.0`. A `0.70` threshold
silently demands **3 of 3**. All 5 withheld show exactly `quality_score=0.667, passed=0`.
`settings.py` already defaults to `0.60`; `.env` overrides it and `.env` wins.

- [ ] T013 In `.env`: `AIQ_VALIDATION_QUALITY_THRESHOLD=0.70` → `0.60`, `AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD=75` → `60`, matching the `settings.py` defaults 010 intended.
- [ ] T014 Log the **effective** `validation_quality_threshold`, `confidence_acceptance_threshold`, `min_validated_positions`, `assessor_agent_count` at run start, so a `.env` override can never again silently negate a code change.

## Step 3 — GATE: measure

- [ ] T015 **GATE** Run `python scripts/score_25q.py` on the clean DB. Record delivered / withheld / delivered-correct plus the 25-row table (qid, locus, supplying source, landed domain, answer, expected) in `specs/011-answer-correctness/results-step1.md`.
- [ ] T016 **Per-source correctness must be in that table.** The single most useful diagnostic this run can produce is whether merged-candidate judging beat `sitemap 7/11 · search 5/12`. If sitemap-supplied accuracy drops, T006's tie-break is too weak.
- [ ] T017 **Check the true negatives did not flip.** `SP-108a` (app retired 2022), `IF-336` (no US misinformation statute — First Amendment), `SP-062` (no national utility payment portal) are currently correct NOs. A wider candidate pool gives more chance to find a spurious yes.

**Stop and read the number before anything below.**

---

## Step 4 — Deliver the link, let the human take the call

**Step 1 landed: 12 → 14 of 25** (22 delivered, 3 withheld, 0 false positives, 285 tests pass).
Verified independently against `bm-sess-6bc586ac55e8`.

The remaining pattern is not a link problem any more. On the cases that did *not* fire True, the
pipeline's link is frequently **as good as or better than the curated ground truth**, the assessor
was right and confident, and the **validator destroyed the answer**:

| Q | Landed | Assessor | Validator | Ground truth |
|---|---|---|---|---|
| IF-011 | `whitehouse.gov/administration/cabinet/` | True @ 95 | `element_absent`, 0.0, ×3 | **exact same URL** |
| IF-340 | `gsa.gov/…/cybersecurity-programs-and-policy` | True @ 95–100, cites FISMA 2014 | `element_absent`, 0.0, ×3 | cisa.gov |
| EGL-321 | `epa.gov/citizen-science` | True @ 90–95 | `confirmed` but judged 0.0 ×3 | citizenscience.gov |
| EGL-036b | `usa.gov/libraries` | True @ 90 → **flipped to False @ 75** | passed the *flipped* answer | **exact same URL** |

Two distinct causes, and they need different fixes:

- **Mechanical (IF-011, IF-340, EGL-036b run 1)** — `verification_outcome=element_absent`. The
  validator could not re-locate the quote on a **truncated** DOM (IF-011's page exceeded the 15k
  limit by 19.5k chars). This is "could not check", not "evidence is bad". The validator already
  treats `target_unreachable` as explicitly **not** a quality failure — truncation is the same class
  of infrastructure failure and is currently scored as if the assessor lied.
- **Judgment (EGL-321)** — evidence `confirmed`; the two models genuinely disagree on whether
  citizen science counts as co-creation of e-services. Neither is obviously wrong. **This is exactly
  what a human reviewer is for.**

**EGL-036b is the worst case in the set**: a mechanical failure triggered a retry, the retry
pressured a correct `True` into a wrong `False`, and the validator then *passed* the wrong answer.
Withholding is bad; silently converting right into wrong is worse.

### Both mechanisms this needs already exist and are unwired

- `best_effort_confidence_ceiling = 74` — defined in `settings.py:58`, range-checked in
  `config/validation.py:47`, and **referenced nowhere in the pipeline**.
- `page_text_truncated` / `page_text_excess_chars` — computed at `agents/assessor/agent.py:511-512`
  and carried on the output, and **never consulted by the validator**.

This is wiring, not new machinery.

### Interface facts — verified 2026-08-21, read before writing code

**A. There is a live config error on `main` right now.** Step 2 lowered
`AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD` 75 → 60 but left
`AIQ_BEST_EFFORT_CONFIDENCE_CEILING=74`. `config/validation.py:47` enforces
`ceiling < threshold`, so `validate_settings()` now raises:

```
ConfigurationError: AIQ_BEST_EFFORT_CONFIDENCE_CEILING (74) must be below
                    AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD (60)
```

The benchmark run did not catch this because `scripts/score_25q.py` never calls
`validate_settings()`. The CLI, API, and portal do. **Fix this first — T022 cannot use a ceiling
of 74 anyway.**

**B. The truncation flag never reaches the validator.**
`page_text_truncated` / `page_text_excess_chars` exist on `AssessorAgentOutput`
(`schemas.py:115-116`) and on `AssessorAgentRun` (`entities.py:314-315`) — but
`_run_output_from_agent_run()` (`retry_loops.py:206-216`) **rebuilds the output without copying
them**, and the validator is *always* fed that reconstruction (`retry_loops.py:~90`), including on
the first, non-retry validation. So the validator sees `page_text_truncated=False` 100% of the
time. **T024 is a silent no-op until this is fixed.**

**C. No new prefill plumbing is needed.** `write_prefill()` (`prefill_writer.py:22-45`) already
accepts `reason` alongside `suggested=True`; `Prefill.reason` (`entities.py:525`) persists it; and
`prefill_writer.py:53` (`target_state = DELIVERED if suggested else terminal_state`) already lands
the unit in `DELIVERED`. Add one `PrefillReason` enum member; change no schemas.

**D. The review portal already has the flagging affordance.** `question.html:45` applies a
`confidence--low` class from `view.below_acceptance_threshold`, and `question.html:67` renders a
banner from `view.reason_tag`. Reuse both; do not invent a new UI concept.

**E. There is no confidence "cap" in code to edit.** The 40s come from *prompt* calibration
(`profiles.py:47-56`: thin evidence "should score in the 30-65 range"). Editing that band moves
positives too. See T027 for the narrow alternative.

### Tasks

- [x] T022 **Fix the config invariant first.** Set `AIQ_BEST_EFFORT_CONFIDENCE_CEILING=55` in `.env` and the `Settings` dataclass default (`settings.py:58`) — both were stuck at 74. `tests/unit/test_config_ceiling_floor.py` asserts `validate_settings(load_settings())` raises nothing, plus the ceiling/threshold boundary directly. **Done, verified.**
- [x] T023 **Never discard a resolved link plus a confident answer.** Implemented at `scheduler.py:669` (the best-effort block ahead of the `no_suggestion(INSUFFICIENT_POSITIONS)` fallback). Two things the plan didn't anticipate, found by running it:
  - `Prefill.__post_init__` (`entities.py:536`) hard-enforced "`suggested=True` implies `reason is None`" — a real invariant, not a bug. Relaxed it to allow exactly one exception: `reason=NEEDS_HUMAN_REVIEW` alongside `suggested=True`. Every other reason still requires `suggested=False`.
  - The unit-state machine (`unit_state.py:24`) only allows `ASSESSING -> {ADJUDICATING, RESOLVING_LINK, NO_SUGGESTION}` — not `-> DELIVERED` directly. Picking the strongest candidate among failed-validation runs is itself an adjudication-shaped decision, so the fix routes through `advance(ADJUDICATING, ...)` before `advance(DELIVERED, ...)`, rather than widening the transition table.
  - Uses the **evidence artifact's own** `resolved_url` (`best_evidence.resolved_url`), not the unit-level portal URL — this reflects one-hop navigation (`AssessorAgentRun.navigated_to_url`), so the delivered link is the actual page the answer came from, per the "final directory" requirement.
  - The validator's own gap text is carried into `unit_context["validator_gaps"]` for reviewer-facing explainability, and `write_prefill` now records `prefill_reason` in unit context even when `suggested=True` (previously only recorded for discards).
  - **Done, verified** — 4 new tests in `tests/unit/test_best_effort_delivery.py`.
- [x] T024 **Stop scoring a truncation artefact as a quality failure.** Both parts done: (a) `_run_output_from_agent_run()` (`retry_loops.py:206`) now copies `page_text_truncated`/`page_text_excess_chars`; (b) `validator/agent.py:129` returns a new `VerificationOutcome.TRUNCATED_UNVERIFIABLE` (added to the enum, `entities.py:120`) before the judgment call when `element_absent` coincides with truncation. "No retry consumption" is implemented in `retry_loops.py:135` — `TRUNCATED_UNVERIFIABLE` short-circuits straight to `VALIDATION_FAILED_TERMINAL` on the FIRST attempt, since re-fetching the same deterministically-truncated page cannot change the outcome; the freed-up run becomes a candidate for T023's best-effort path instead. **Done, verified** — `tests/unit/test_truncated_validation.py` (3 tests) + one short-circuit test in `test_retry_addendum_wording.py`.
- [x] T025 **Stop the retry loop flipping a correct answer.** `retry_loops.py:157` now branches on `validation.verification_outcome`: `ELEMENT_ABSENT`/`TEXT_MISMATCH` get a fixed re-cite addendum ("Your ANSWER is not in question ... Do not change your answer"); every other failure (judgment-level) still gets the original `validation.gaps` verbatim. **Done, verified** — `tests/unit/test_retry_addendum_wording.py` asserts both branches by content, not just structure.
- [x] T026 Regression tests — all four written and passing (see T022-T025 entries above for which file covers which). Full suite: 289 passed (275 pre-existing + 14 new), 0 failures.

### T027 — the confidence bump, and an honest caveat

Six delivered negatives sit at exactly 40 because the prompt tells the model that thin evidence
belongs in 30-65 (`profiles.py:47-56`). Two ways to lift it:

- **Broad (not recommended):** raise the prompt band. This inflates *every* thin-evidence answer,
  including the wrong ones, and would push some above 65 where the validator starts failing them on
  `confidence_proportionate` — the exact gap that hit EGL-036b at 75. It buys presentation and
  costs accuracy.
- **Narrow (recommended):** apply a floor of **55** at prefill-write time to negatives that
  **passed validation**. A validated negative means the pipeline looked, anchored the finding, and
  a second model confirmed the anchor supports it — that is genuinely more trustworthy than the raw
  evidence-weight number conveys. Leave best-effort/`needs_human_review` deliveries at their capped
  value so the two tiers stay visually distinct.

- [x] T027 Implemented as a dedicated setting, `validated_negative_confidence_floor: int = 55` (`settings.py:59`, env `AIQ_VALIDATED_NEGATIVE_CONFIDENCE_FLOOR`) — kept separate from `best_effort_confidence_ceiling` even though both start at 55, because they mean different things (one is a cap on unconfirmed answers, the other a floor on confirmed ones) and shouldn't be forced to move together later. Applied at `scheduler.py:825`, only on the `candidate_answer is False` branch of the adjudicated-delivery path — never touches the T023 best-effort path. **Done, verified** — 2 of the 4 tests in `test_best_effort_delivery.py` cover this directly, including that best-effort delivery is NOT floored.

> **Confidence is presentation, not correctness.** T027 changes how an answer *reads*; it makes no
> answer more right, and raising it on an unvalidated answer is just laundering. The correctness
> gain in this step is T023 + T024. Report the two separately.

- [x] T028 **GATE** Review portal fallback implemented: `review/query.py` (`build_question_review`) now falls back to `repo.latest_prefill(...)` when no adjudication result exists. Verified with unit tests.

---

## Step 5 — Fill rate is nearly maxed; the remaining gain is all in false negatives

### The measurement that reframes the goal

From `data/usa_sample.db` (25-question USA sample, seed 42):

| | count | note |
|---|---|---|
| Delivered | 22 / 25 (**88%**) | 11 `True`, 11 `False` |
| `no_suggestion` | 3 / 25 | all `insufficient_positions` — **T023 already recovers these** |

So raw fill rate goes to ~100% with Step 4 alone. **There is almost no withheld-answer problem left.**

Cross-referencing the 18 non-`True` answers against `USA_25Q_GAP_ANALYSIS.md`:

| verdict | count | meaning |
|---|---|---|
| **False negative** | **11** | the service exists, on a page the pipeline never looked at |
| True negative | 3 | `#336` (First Amendment), `#062/#063` (utilities are municipal), `#108a` (app retired 2022) |
| Borderline | 1 | `#036b` |
| Validator drop | 3 | `#124`, `#166`, `#166b` — Step 4 addresses |

Correct today ≈ **10/25 (40%)**. Ceiling if the 11 flip ≈ **21/25 (84%)**.
Every remaining point is a false negative. Nothing else is worth touching first.

### The single root cause

`scheduler.py:619` gates the entire second-look mechanism:

```python
link_needs_retry = bool(all_runs) and all(
    r.portal_unreachable or r.link_likely_wrong for r in all_runs
)
```

An assessor that reads `usa.gov/agency-index` fine and confidently answers *"No — this A-Z index
lists websites and phone numbers but omits leader names"* sets **neither** flag. No retry fires.
That answer is validated, delivered, and wrong — the Cabinet list is one click away on
`whitehouse.gov`.

Two pieces of the codebase already admit this in their own comments:

- `profiles.py:162` — "`link_likely_wrong` was built to catch this and **never fired once in 50
  questions**." The retry gate is therefore live only for `portal_unreachable`.
- `profiles.py:176` — one-hop navigation was the replacement, but its prompt says report `-1`
  "whenever you already found … a confident, well-evidenced No, on THIS page." **A confident No is
  defined as terminal.**

**Negative evidence is asymmetric.** Finding the service proves `Yes`. Not finding it on one page
proves nothing at all. The pipeline currently treats both as equally conclusive, and that single
asymmetry error accounts for all 11 false negatives.

> The corollary sets the whole design rule for this step: **do not lower the bar for `Yes`.** A
> `Yes` still needs an anchored quote that survives validation. We are only refusing to accept an
> *unexamined* `No`. Any change that makes `Yes` cheaper buys accuracy on paper and loses it in
> reality — that is Finding 2's mistake repeated.

### Recovering these eleven is not the same as preventing the next eleven

T040–T043 are **recovery**: each is aimed at a failure we can point to in a 25-question sample
someone hand-checked against real-world search. That is exactly the wrong basis for the general
case. On the next country there is no gap analysis, no Antigravity column, and no list of which
`No`s are wrong — and a false negative is **invisible by construction**: it arrives as a confident,
validated, well-justified answer that looks identical to a correct one. Nothing in the record
distinguishes *"searched hard, genuinely absent"* from *"looked once at the wrong page"*.

So the step needs a rule that holds without a ground-truth column, and it follows directly from the
asymmetry above:

> **A `No` may only be delivered as a confident `No` if it can show it went looking.**
> Otherwise it is not a finding, it is an absence of evidence — and Step 4 already built the right
> place to put that: `NEEDS_HUMAN_REVIEW`.

This reuses machinery that exists rather than adding a tier: the flagged-delivery path, the
confidence ceiling, the `validator_gaps` context, and the portal's `reason_tag` banner all landed in
T023. An unearned `No` is precisely the case that path was built for — a real answer nobody could
confirm.

**Honest tension, stated up front:** this trades *clean* fill rate for correctness. Some answers
that ship today as confident `No`s will ship as flagged `No`s instead. That is the intended
direction — a wrong answer a reviewer trusts is worse than a right answer a reviewer checks — but it
means T048 must report flagged and clean deliveries as separate numbers, or the step will look like
a regression.

### Tasks

- [x] T040 **Let one-hop navigation cross domains — it is currently stricter than our own policy.**
  `_extract_same_domain_links()` (`agents/assessor/agent.py:306`) hard-drops every link where
  `urlparse(href).netloc != base_domain`. But T030 (spec 010) already relaxed `evidence_permitted()`
  so that *any* same-country government domain is admissible. The extractor is enforcing a rule the
  locus layer no longer has. Widen it to any host passing `is_government_domain(href, country_id)`
  **and** `check_admissible(href)`, keeping same-domain links ranked first. This is a
  consistency fix, not a new capability. Directly reachable: `#011` (`usa.gov` links to
  `whitehouse.gov/administration/cabinet`), `#337`, `#338`, `#022/#024`. **Do this first — it is the
  smallest diff with the clearest justification.**

- [x] T041 **A unanimous `No` must survive a second look before it is delivered.** Extend the
  `link_needs_retry` condition: also retry when every run answered `False` **and** a
  negative-recheck has not yet been spent for this unit (track `negative_recheck_done` in
  `unit_data`, budgeted separately from `MAX_LINK_RETRIES = 3` so it cannot be starved by earlier
  unreachable-retries). The existing machinery already does the rest — `tried_urls` makes search
  surface a different candidate, and the recursion at `scheduler.py:660` is unchanged. Outcomes:
  second page says `Yes` ⇒ deliver `Yes`; second page also says `No` ⇒ deliver `No`, now genuinely
  earned. This is the lever for ~10 of the 11.

- [x] T042 **Make the second look ask a different question, or T041 buys nothing.** Re-resolving
  with the same `search_query` and one URL excluded returns the next page on the *same wrong topic* —
  `#022/#024` would walk `usa.gov/accessibility` → the next Section 508 page, never reaching
  `login.gov`. On a negative recheck, build the query from the question's `what` criteria rather
  than its `title` (both are on the question record; `chain.py` already accepts `widened_query`,
  `relevance_text`, and `relevance_detail`). This is what breaks the keyword traps the gap analysis
  named — "accessibility", "privacy", "education".

- [x] T043 **Reject frozen archive snapshots.** `#321` resolved to
  `19january2021snapshot.epa.gov/…`, a 2021 archive, and was judged as if it were live. Add a host
  pattern check to `check_admissible()` (`linkresolution/admissibility.py`) alongside the existing
  `_DEAD_SHORTENER_HOSTS` / `_NON_CONTENT_SUBDOMAIN_LABELS` rules. Narrow, mechanical, one question.

- [x] T044 **Guard both directions explicitly — one number cannot see either failure.** The risk of
  T041/T042 is trading 11 false negatives for some number of false *positives*, and the risk of T046
  is flagging negatives that were fine. Assert both as named benchmark checks, not as an aggregate:
  **(a)** `#336`, `#062/#063`, `#108a` are known-correct `No`s and must still be `No` — and must
  still be *unflagged* — after a second look; **(b)** the 11 known false negatives must flip to
  `Yes` or, failing that, to flagged. An accuracy number that improves while (a) flips is a
  regression wearing a better number.

- [x] T046 **The negative delivery gate — the one rule that generalises past this sample.** At the
  point a `No` is about to be written as a confident prefill (`scheduler.py`, the adjudicated-
  delivery path where T027's floor now applies), require that the unit can show it looked: at least
  **two distinct admissible pages examined**, under at least **two distinct queries** (T042 supplies
  the second). A `No` meeting that bar delivers as today, floored by
  `validated_negative_confidence_floor`. A `No` that does **not** — one page, one query, nothing
  followed — delivers via the T023 path instead: `suggested=True`, `reason=NEEDS_HUMAN_REVIEW`,
  capped at `best_effort_confidence_ceiling`, with the reason text saying plainly that the answer
  rests on a single page. No new state, no new reason code, no new UI concept. Note the ordering
  dependency: this gate is only meaningful **after** T041/T042 exist to supply a second page — before
  them it would flag nearly every negative.

- [x] T047 **Record what the negative actually looked at, so the next false negative is findable.**
  A false negative currently leaves no trace distinguishing it from a true one. The unit already
  accumulates `tried_urls`, `blocked_domains`, `link_retry_count`, and per-run
  `navigated_to_url`; none of it survives onto the prefill. Carry a compact negative-provenance
  record (pages examined, queries used, domains blocked) into `unit_context` beside T023's
  `validator_gaps`. This is what makes T046's gate auditable rather than a magic threshold, gives
  the reviewer the "we checked these three pages" line that makes a flagged `No` actionable, and
  turns the next country's false negatives into something greppable instead of something that needs
  a hand-built gap analysis to discover.

- [x] T048 **GATE** Re-run the 25-question sample and record **six** numbers separately — an
  aggregate hides every failure this step is about: (1) fill rate split into **clean vs flagged**
  deliveries, (2) correct-answer rate, (3) true-negative retention (T044a), (4) false-negative
  recovery (T044b), (5) **flagging precision** — of the negatives T046 flagged, how many were
  actually wrong; if that is near zero the gate is miscalibrated and costs reviewer trust, and
  (6) **cost/latency delta**. T041 roughly doubles assessor work on negative units — in this sample
  ~11 units gain a full resolve+assess+validate round. That is the price of the step and it should
  be stated, not discovered.

### Explicitly not doing in this step

- **`#030` (`sam.gov/fpds`)** — a client-side-rendered search widget with no pre-rendered rows.
  Fixing it means executing the widget's query, which is a scraping capability, not a resolution
  fix. One question; revisit only if the pattern recurs across countries.
- **Raising the prompt's confidence band** — see the Step 4 caveat. Confidence is presentation.
- **Per-country domain allow-lists** (`data.gov`, `cio.gov`, …) — recommendation 1 of the gap
  analysis, now obsolete: T030 (spec 010) already admits any same-country government domain, so a
  hand-maintained alias list per federated country would add upkeep for no additional reach.

---

## Then improve (only after T015 has a number)

- [ ] T018 Try `AIQ_ASSESSOR_AGENT_COUNT=2` and re-measure. This activates all the dormant machinery at once (agreement → resolver). Worth exactly one measured experiment: if the number does not move, keep it at 1 and halve the cost.
- [ ] T019 Audit `EGL-321` — assessor said True/95 with strong reasoning; validator rejected 0/3 arguing citizen science ≠ co-creation of e-services. The validator's reading is defensible and the fixture may be wrong. Decide, record in the fixture `note`.
- [ ] T020 `SP-166b` is structurally unreachable: reference is `enviroflash.info`, not `.gov`, so `is_government_domain()` rejects it by design. Add `airnow.gov` as an accepted alternative or mark permanently out of scope.
- [x] T021 ~~Fix the recursive link-retry call to `process_unit` in `scheduler.py` not forwarding `resolve_only`~~ — **already fixed** during Step 1–3; verified at `scheduler.py:672`.

---

## Explicitly not doing

**Not changing the tech stack.** The assessor reasons correctly on every miss. The defect is
candidate selection in code we own.

**Not deleting the dormant 2-agent path.** 010 already ran that experiment. T018 tests whether it
earns its keep instead.

**Not adding a third fix before the first two are measured.**

---

## Risks

| Risk | Mitigation |
|---|---|
| Merged judging loses sitemap's 63% | T006 makes the portal the tie-break, not a coin flip; T016 measures per-source accuracy explicitly |
| A wider candidate pool produces spurious YESes | T017 checks the three known true negatives before anything proceeds |
| +1 search call per unit | T008 sizes it before the run; fall back to gating the second pass on a weak sitemap score |
| Two conflicting "correct" counts persist | T001 collapses them to one *before* any change is measured |
| The next plausible-sounding fix is also wrong | Finding 2 is the precedent — every step here has a measurement gate attached, and no step is judged by whether it sounds right |

---

## Appendix — Phase T: one LangSmith trace per run (done, 2026-08-21)

A `run_batch` over N questions produced N+ separate root traces. `safe_trace()` always accepted a
`parent`, but no caller passed one — every stage relied on ambient contextvar propagation across
`asyncio.TaskGroup`/`gather` boundaries, which does not reliably nest concurrent spans.

Fixed by threading the parent `RunTree` explicitly:
`batch_trace → unit_trace → agent_trace / validation_trace / adjudication_trace → confidence_gate_trace`.

- [x] `SafeRunHandle.run_tree` property (+ `NoOpRunHandle.run_tree = None`) in `src/core/telemetry/langsmith_tracing.py`
- [x] Optional `parent` on `unit_trace`, `agent_trace`, `confidence_gate_trace`, `validation_trace`, `adjudication_trace`; `batch_trace` unchanged as root
- [x] `scheduler.py`: `batch_run=batch_span.run_tree` → `process_unit` → `unit_trace(parent=…)`; `parent=root_run.run_tree` into `assessor_node` and `run_validation_retry_loop`; `batch_run` propagated through the recursive retry
- [x] `retry_loops.py`, `confidence_gate.py`, `agents/assessor/agent.py`: `parent` threaded to every child span
- [x] `281 passed` — all new parameters optional, backward compatible
