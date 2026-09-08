# Retrieval Pipeline Tuning — Changelog

Goal: improve the AI prefill link-resolution pipeline's ability to reliably
discover authoritative source links for national-level survey questions
(USA + Denmark), without hardcoding answers to specific questions.

All changes below are structural, apply to every question/country routed
through the chain, and are still sitting **uncommitted in the working tree**
per the session's constraints.

## Evaluation harness

`scripts/eval_national_25q.py` builds a fresh `national_osi` project (US +
DK), ingests Denmark's real MSQ PDF (`understanding docs/Denmark - MS MSQ
2024.pdf`) so the `msq` source has real candidates, and runs
`resolve_only=True` link resolution for 25 randomly sampled national
indicators (seed 42) against both country portals — 50 resolutions per run.
No ground-truth fixture exists for this dataset (by design, per the task
scope), so results are captured for inspection/comparison rather than
scored automatically; correctness was spot-checked against live web search
for a sample of results.

Runs are archived in this directory:
- `baseline_v0.{log,json}` — before any pipeline changes.
- `tuned_v1.{log,json}` — after fix #1 (sitemap semantic validation).
- `tuned_v2.{log,json}` — after fix #2 (jurisdiction hint), on top of fix #1.

Resolution rate held at **50/50 across all three runs** — neither fix
reduced coverage, only precision.

## Fix #1 — sitemap solo-win now requires semantic confirmation

**File:** `src/shared/tools/linkresolution/chain.py`

**Gap:** the `"search"` step in the resolution chain tries the portal's own
sitemap (pure lexical slug-word overlap, `sources/sitemap.py`) and live
search, then adjudicates between the two with the `choose_best()` LLM
judge — but only when *both* returned something. When search came back
empty (all candidates non-government, archived, or otherwise rejected) and
only the sitemap had a hit, that lexical-only match was returned directly
as "resolved" with no semantic check at all. A sitemap slug can match on
frame words alone (see `_match_slug` in `sitemap.py`) and produce a
confident-looking wrong answer.

**Observed in baseline:**
- DK `#005 Sitemap/Index` resolved to
  `borger.dk/kampagnesider/efter-arbejdsskade-...` — an unrelated
  workplace-injury/education page, matched purely because "sitemap" is a
  generic navigational term.
- US `#007 Social networking features` resolved to `usa.gov/features` on
  the word "features" alone.

**Fix:** a sitemap-only win is now run through `choose_best()` exactly like
every other single-candidate source (`msq`, `prior_survey_kb`) before being
accepted. If the judge abstains, the sitemap attempt is marked unusable and
recorded as rejected in the history, and resolution falls through to the
portal-default homepage fallback rather than returning a wrong deep link.

**Result (tuned_v1 vs baseline):** both false positives above corrected —
DK #005 and US #007 both now correctly fall back to the portal homepage
instead of returning a wrong, confident-looking deep link. `sitemap`
solo-wins dropped from 7 → 4 of 50; `search`/`portal_default` picked up the
difference. Resolution rate unchanged (50/50).

## Fix #2 — relevance judge is told the required jurisdiction level

**Files:** `src/shared/reference/domains.py` (new `jurisdiction_hint()`),
`src/shared/tools/linkresolution/chain.py`,
`src/shared/tools/linkresolution/sources/search.py`

**Gap:** government-domain admissibility (`is_government_domain()`,
`resolve_admissible_domain_suffixes()`) accepts any domain on the
country's TLD/ccTLD set — for the US that is `{gov, mil}`, which admits a
*state* DMV site (`pa.gov`) exactly as readily as the *national* aggregator
(`usa.gov/state-motor-vehicle-services`). The semantic relevance judge
(`choose_best()`) never received any signal about which government level a
national-OSI assessment actually requires, so a topically-correct but
jurisdictionally-wrong sub-national page could win outright.

**Observed in baseline/tuned_v1:** US `#046 Registration or renewal for a
vehicle` resolved to `pa.gov/services/dmv/renew-vehicle-registration` — a
single state's page — instead of the national aggregator. Confirmed via
independent web search that `usa.gov/state-motor-vehicle-services` is the
correct national-level answer and does exist.

**Fix:** added `jurisdiction_hint(country_id)` to
`shared/reference/domains.py`, reusing the same 2-letter-ISO-code vs.
3-letter-city-code distinction the domain-suffix resolver already uses. It
returns a one-paragraph instruction — "this is a NATIONAL assessment for
{country}; a state/provincial/regional/municipal page does not satisfy
this unless it is the country's own designated national aggregator" (or
the equivalent local-government wording for city/LOSI units) — and is
appended to every `choose_best()` prompt's `what` field, in both
`chain.py`'s three call sites and `search.py`'s internal candidate-pool
adjudication. This generalizes across every country and every indicator;
nothing is keyed to a specific question.

**Result (tuned_v2 vs tuned_v1):** US #046 flipped from `pa.gov`
(wrong jurisdiction) directly to `usa.gov/state-motor-vehicle-services`
(the confirmed-correct national aggregator). DK `#09a` AI chatbot also
stopped accepting a municipal-only news article and fell back to the
portal homepage instead. One apparent regression was investigated (US
`#343` cloud strategy, previously `cloud.cio.gov/strategy/`, now
`portal_default`) and ruled out as caused by this fix — the search API's
candidate pool that run contained zero admissible government-domain
results at all (AWS/Intel/Deloitte blog posts, one archived
`obamawhitehouse.archives.gov` page); `cloud.cio.gov` simply wasn't
surfaced by the live search API on that run. This is live-search
run-to-run variance, not a pipeline regression — the by-source and
resolved-count totals stayed the same shape across the three runs given
that variance.

## Verified against live web search (not overfit to any dataset)

- `cloud.cio.gov/strategy/` confirmed as the official "Cloud Smart" federal
  cloud strategy site.
- `usa.gov/state-motor-vehicle-services` confirmed as USA.gov's own
  national aggregator for state DMV services.
- GAO FraudNet / oversight.gov confirmed as legitimate federal corruption-
  reporting channels (baseline's `gao.gov/about/what-gao-does/fraud` is
  plausible, not definitively wrong — left alone).

## Not changed / open items for a future iteration

- Query reformulation when search returns zero admissible candidates (DK
  `#313` rural online services never found a strong candidate in any run;
  US `#343` is subject to the same live-search-variance risk shown above).
  The production scheduler (`orchestration/scheduler.py`) already retries
  with a `widened_query` once the Assessor Agent judges fetched content
  insufficient — that retry path is legitimately out of scope for a
  `resolve_only` harness with no ground truth to judge sufficiency against,
  but a static (non-assessor-gated) widen-and-retry inside `chain.py`
  itself, for the case where the *first* search attempt returns zero
  admissible candidates, would be a reasonable next structural fix.
- The `_match_slug` lexical threshold in `sitemap.py` was left as-is;
  fix #1's judge check is a sufficient safety net without narrowing sitemap
  recall further.
