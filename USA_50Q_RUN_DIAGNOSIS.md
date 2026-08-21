# USA 50-Question Run — Why Almost Everything Came Back "No"

**Run analysed:** `data/usa_sample_50_v4.db` (session `usa-sample-2026-workflow-session`, 2026-08-21 05:19) — the latest of four 50-question runs.
**Portal under test:** `https://www.usa.gov` (US)

## 1. What the run actually produced

| Run | Yes | No | No suggestion |
|-----|-----|----|---------------|
| usa_sample_50_v1 | 11 | 36 | 3 |
| usa_sample_50_v2 | 9  | 37 | 4 |
| usa_sample_50_v3 | 8  | 37 | 5 |
| **usa_sample_50_v4 (latest)** | **10** | **36** | **4** |

The result is flat across all four runs — this is systemic, not run-to-run noise.

Supporting telemetry from v4:

- **210 page fetches, 100% on `usa.gov`** (`www.usa.gov` 195, `1.usa.gov` 6, `go.usa.gov` 6, `my.usa.gov` 3). Zero fetches to `data.gov`, `sam.gov`, `usaspending.gov`, `irs.gov`, `travel.state.gov`, `uscourts.gov`, `regulations.gov`.
- **21/50 questions were answered against a URL supplied by `portal_default`** — i.e. the fallback, because link resolution produced nothing usable. 12 of those are literally `https://www.usa.gov/`.
- **48/50 units never retried link resolution** (`link_retry_count == 0`). The "relaxed retry" that is supposed to widen the search to any government domain essentially never ran.
- **16/50 search attempts were rejected** with `URL points to a raw data file (csv), not a browsable page` — all `analytics.usa.gov/**/*.csv`.
- **The assessor set `link_likely_wrong` only 3 times in 68 runs**, while writing `fill_gap_reason = "not present anywhere on this page"` **37 times**.

That last pair is the whole story in one line: the model kept saying *"the thing isn't on this page"* and the pipeline kept hearing *"the thing doesn't exist"*.

## 2. Root causes — in plain bullets

### A. The pipeline judged the right question against the wrong page

Search returns the **first URL that is on an allowed domain**. There is no check that the page is even *about* the topic. Actual pairings from this run:

| Question | URL it was judged on |
|---|---|
| #003 Search feature | `usa.gov/website-analytics/` |
| #055 Online land title registration | `usa.gov/confirm-voter-registration` |
| #062,#063 Water/energy utility payment | `usa.gov/report-incorrect-benefit-payments` |
| #092 Government expenditure — Health | `usa.gov/tribes` |
| #108a Mobile services — Education | `usa.gov/unclaimed-money` |
| #321 Co-creation — Environment | `usa.gov/disability-services` |
| #036b Access to physical spaces | a 2016 blog post about sharing personal info |

The only filter applied is `_domain_ok()` in `src/shared/tools/linkresolution/sources/search.py:255-260`. Relevance is never scored.

### B. One bad candidate kills the entire search source

`search_for_link()` returns **one** `ResolutionAttempt`. `resolve_link()` then runs `check_usable()` on it (`src/shared/tools/linkresolution/chain.py:117-124`). If that one candidate fails — 16 times it was an `analytics.usa.gov` CSV — the whole `search` source is marked unusable and the chain drops straight to `portal_default` (the homepage). **Candidate #2 from the same result list is never looked at.**

### C. The retry gate almost never opens

`src/orchestration/scheduler.py:544-547` fires a link retry only when **every** agent reports `portal_unreachable` **or** `link_likely_wrong`. But the prompt explicitly tells the model *not* to set `link_likely_wrong` when "the feature is genuinely absent from an otherwise-relevant page" (`src/agents/assessor/agent.py:79-87`). So a confident wrong-page "No" looks identical to a correct "No", the retry never fires, and the relaxed any-government-domain search (`scheduler.py:320-329`) never runs. 48/50 units.

### D. Page text is cut at 15,000 characters — and paginated pages are never paginated

`src/shared/prompts/profiles.py:275` does `page_text[:15000]`.

Worse: `usa.gov/agency-index` server-renders **only the "A" entries** (17,797 chars, ending at "Arctic Research Commission"). "Department of Education" and "Environmental Protection Agency" are **not in the HTML at all** — they live on `usa.gov/agency-index/e`, which the pipeline never visits.

This single fact produced these false negatives: **#103 (Education link), #161 (Environment link), #011 (heads of department), #337 (National CIO)** — all judged "No" against a page containing only agencies starting with "A".

### E. One-hop navigation cannot leave the portal domain

`_extract_same_domain_links()` (`src/agents/assessor/agent.py:293-330`) filters with `urlparse(href).netloc.lower() != base_domain`. Even when `usa.gov` links straight out to `irs.gov`, `sam.gov`, or `data.gov`, those links are stripped before the model sees them.

### F. Search queries are too thin

The query is just `question.title` (`scheduler.py:337`) plus a `site:` operator. "Search feature", "Income taxes", "Long term care" are far too generic to rank a specific page, which is exactly why the results collapse onto homepages and unrelated topics.

### G. The DuckDuckGo branch short-circuits its own fallbacks

In `search_for_link()`, if DDG returns links but none pass the domain check, it `return`s immediately — skipping the LLM deep-link resolver (step 3) and the Bing fallback (step 4) entirely.

### H. 35 of 50 questions are configured `national_portal_only`

This is a **data/config** issue, not a code bug, but it dominates the score. Under `evidence_permitted()` (`src/shared/tools/linkresolution/locus.py`), evidence on `data.gov`, `regulations.gov`, `irs.gov`, `cio.gov` or `travel.state.gov` **cannot count** for these questions. In the US the national portal is a thin signposting site — nearly all real service delivery lives on separate `.gov` domains. Either the locus mapping or the "national portal" definition for the US needs revisiting before any score from this run is meaningful.

## 3. Web validation of the "No" answers

Every "No" below was checked against live sources.

### Confirmed false negatives — evidence exists *on usa.gov itself*

| # | Question | Reality | Cause |
|---|---|---|---|
| #003 | Search feature | usa.gov has a search box in the header, per federal site-search standards | Judged on `/website-analytics/` (A) |
| #095 | Online services — Health | `usa.gov/health` lists health insurance, medical bills, mental health, substance abuse, COVID-19, MedlinePlus, state health departments | Judged on the homepage (B) |
| #103 | Ministerial link — Education | `usa.gov/agency-index/e` links to `ed.gov` | A–Z pagination + 15k cut (D) |
| #161 | Ministerial link — Environment | Same page links to `epa.gov` | Same (D) |
| #119 | Ministerial link — Employment | Agency index links to `dol.gov` | Judged on a topic page instead (A) |

### False negatives caused by the usa.gov domain lock (`any_government_domain` questions that were never allowed to leave the portal)

| # | Question | Evidence that exists |
|---|---|---|
| #030 | Procurement results | `sam.gov/fpds` contract award search; `usaspending.gov` award search (FFATA-mandated) |
| #043 | Income taxes *(no suggestion)* | IRS Free File and Free File Fillable Forms at `irs.gov/freefile` |
| #047 | Online police declaration | FBI Internet Crime Complaint Center, `ic3.gov` — "File a Complaint" |
| #092 | Expenditure — Health | `usaspending.gov`, `fiscaldata.treasury.gov` Monthly Treasury Statement |
| #105 | Expenditure — Education | Same, plus CBO open data repository |
| #173 | Policies — Justice | `justice.gov` policy collections |
| #183 | Access to justice information | PACER (`pacer.uscourts.gov`) + CM/ECF e-filing, 24/7 public case access |
| #321 | Co-creation — Environment | `citizenscience.gov`, EPA participatory-science programs, `challenge.gov` |

### "Correct under the locus rule, wrong under the methodology" — evidence exists on another `.gov`, but the question is flagged `national_portal_only`

| # | Question | Where it actually lives |
|---|---|---|
| #128, #141, #170, #304 | Open/budget datasets (Employment, Social Protection, Environment, Education) | `catalog.data.gov` — mandated by the OPEN Government Data Act |
| #109, #180, #330–#335 | Online consultations / inclusion of voices | `regulations.gov` — 160+ agencies, public comment under the APA |
| #337 | National CIO | Greg Barbaccia, US Federal CIO (OMB / `cio.gov`) |
| #340 | Cybersecurity legislation | FISMA; Cybersecurity Information Sharing Act 2015 (extended to Sept 2026) — `cisa.gov` |
| #341 | Open Government Data legislation | OPEN Government Data Act, Title II of the Evidence Act, PL 115-435 |
| #045 | Entry/transit visa | DS-160 fully online at `ceac.state.gov/genniv/` |
| #022,#024 | Access to own data | `ssa.gov/myaccount`, IRS online account, `login.gov` |
| #150 | Long-term care | `longtermcare.acl.gov` / `acl.gov/ltc` |
| #108b, #137b, #166b | SMS alerts (Education, Social Protection, Environment) | GovDelivery SMS subscriptions run by EPA, FEMA, Dept of Education and others |

### Genuinely correct "No"

- **#336 Legislation against misinformation** — the US has no such statute; false speech is broadly protected by the First Amendment (CRS IF12180).
- **#055 Online land title registration** — deed recording in the US is a county function (Recorder of Deeds / County Clerk). No national online system exists.
- **#062,#063 Water/energy utility payment** — US utilities are municipal or private; no federal payment channel.
- **#166 Online services — Environment** — usa.gov has no Environment topic section (verified against the live homepage topic list).
- **#011 Names and titles of heads of department** — verified: `usa.gov/agency-index/e` gives websites and contact info but **no** leadership names or titles.
- **#036b Physical spaces**, **#087 Previous transactions** — no equivalent on usa.gov.

### Pipeline failures (no answer at all)

- **#043, #124, #137** — `insufficient_positions`: fewer than `assessor_agent_count` (2) runs reached `validated_pass`. 6 runs ended `validation_failed_terminal`, 16 stayed `assessed`.
- **#320** — `access_boundary`: an authentication wall was reported and the unit was abandoned rather than re-resolved.

## 4. Fixes, in priority order

### P0 — Retrieval (this alone should move most of the "No"s)

1. **Score search candidates for relevance, not just domain.** Rank the top ~10 results by title/URL/snippet overlap with the question's `title` + `what`, and only then apply the domain filter. Pick the best, not the first.
2. **Return a ranked list, not one candidate.** Have `search_for_link()` return N candidates and let `resolve_link()` walk them, applying `check_usable()` per candidate. A single CSV hit must not collapse the source to `portal_default`. *(Highest-value single change: directly recovers the 16 CSV-rejected units.)*
3. **Stop treating the homepage as an answer.** Never deliver a prefill judged against the bare portal root — treat `portal_default` as "resolution failed" and force a retry with a richer query.
4. **Widen the retry gate.** Trigger a link retry whenever `fill_gap_reason` indicates a page/coverage problem (`"not present anywhere on this page"`, `"wrong page for the indicator"`), not only on the rarely-set `link_likely_wrong`. Keep `MAX_LINK_RETRIES = 3`.
5. **Fix the DDG short-circuit** in `search_for_link()` — fall through to the LLM resolver and Bing instead of returning early when no DDG result passes the domain check.

### P1 — Page comprehension

6. **Handle paginated / lettered indexes.** Detect A–Z or numbered pagination and fetch the relevant shard (`/agency-index/e` for "Education"), or fetch all shards for directory-type questions.
7. **Replace the flat 15k truncation with relevance-windowed extraction** — chunk the page, keep the chunks that match the question's key terms, and state explicitly in the prompt when content was omitted.
8. **Let one-hop navigation cross to other government domains** when `evidence_locus == any_government_domain`, instead of the current strict `netloc == base_domain` filter.

### P2 — Query and scope

9. **Build richer search queries** from `title` + key terms from `what` + the country name, rather than `title` alone.
10. **Re-audit `evidence_locus` for the 35 `national_portal_only` questions.** For a federated country like the US, either broaden the accepted set (`data.gov`, `regulations.gov`, `irs.gov`, `cio.gov`, `usaspending.gov`, `travel.state.gov`) or register those as portal aliases on the `TargetPortal` record.
11. **Retry access boundaries** rather than terminating the unit on the first authentication wall (#320).

### P3 — Guardrails

12. **Add a smoke assertion**: if more than ~20% of units in a run resolve to `portal_default`, or more than ~90% of fetches hit a single domain, fail the run loudly instead of publishing the scores.
13. **Persist the "why" of every No** — the pairing of `fill_gap_reason` with the resolved URL is what made this diagnosis possible; surface it in the run report by default.
