# Link Resolution Fix Plan

**Supersedes the first draft of this file.** Folds in the agreed escalation policy.

**Context:** the [USA 50-question diagnosis](USA_50Q_RUN_DIAGNOSIS.md) traced the 36/50 "No" rate to link resolution putting the right question in front of the wrong page.

---

## 1. Guiding principles

The search policy, as agreed:

1. **Portal first.** Try the designated national portal (`usa.gov`) before anything else.
2. **Widen on failure.** If the portal round genuinely fails, surf the wider government web.
3. **Stay authoritative.** Whatever is reached must be a real government content page — not a blog, news item, press release, dashboard, or raw data file.

The code already intends exactly this ([chain.py:73-84](src/shared/tools/linkresolution/chain.py#L73-L84)). It fails on all three:

| Principle | Why it fails today |
|---|---|
| Portal first | Works — but via a blanket `site:` operator that returns `analytics.usa.gov` CSVs and dead shorteners |
| Widen on failure | The failure signal (`link_likely_wrong`) fired **3 times in 68 runs**. Exactly **1 unit of 50** ever reached the widened search |
| Stay authoritative | `is_government_domain()` accepts *any* domain on a country's ccTLD (`some-random-blog.dk` → True) and any path on a gov domain (`usa.gov/blog/2016/...` → True) |

### The one architectural rule

**Judgement decides when to widen. Code decides what is admissible.**

- *"Did I look in the right place on this portal?"* → **prompt**. Needs reading comprehension; the model does this well.
- *"Is this an official government domain and a real content page?"* → **code**. Never the prompt. A model asked to judge whether a blog counts as government will rationalise its way to yes, especially once it thinks it has found an answer.

---

## 2. Workstreams

### W1 — Escalation signal *(unblocks principle 2; nothing else works without it)*

The agent currently cannot distinguish *"the portal genuinely lacks this"* from *"I never found the right page."* Both surface as a confident No.

**Change:** replace the `link_likely_wrong` gate with a **portal-coverage verdict**. Ask about the *search*, not the *link*:

> Did you reach a page on this portal that would plausibly carry this feature if it existed — a topic hub, a service index, a directory? Or did you only ever see pages unrelated to the question?

- Add `portal_coverage: "found_relevant_page" | "never_found_relevant_page"` to `_RESPONSE_SCHEMA` ([agent.py:38-110](src/agents/assessor/agent.py#L38-L110)), plus `AssessorAgentOutput` ([schemas.py:112](src/shared/state/schemas.py#L112)) and `AssessorAgentRun` ([entities.py:300](src/shared/state/entities.py#L300)).
- Escalate when **all** agents report `never_found_relevant_page` — replacing the `link_likely_wrong` condition at [scheduler.py:544-547](src/orchestration/scheduler.py#L544-L547).
- Keep `link_likely_wrong` as a secondary trigger; do not remove it.

This correctly keeps #336 (no US misinformation law — the agent *did* reach `laws-and-legal-issues`) as a No, while escalating #030 (procurement — the agent only ever saw the homepage).

**Tests:** extend `tests/unit/test_prefill_pipeline.py` and `test_resolver.py` with a fake agent returning each verdict; assert escalation fires only on `never_found_relevant_page`.

**Size:** S. **Blocks:** W4.

---

### W2 — Admissibility: two checks, not one *(principle 3)*

`is_government_domain()` ([search.py:48-74](src/shared/tools/linkresolution/sources/search.py#L48-L74)) is doing two jobs badly. Split it.

**(a) Domain authority — replace the label heuristic with a registry.**

- US: GSA publishes the complete `.gov` domain list as CSV. Vendor it, refresh periodically.
- Other countries: a curated per-country allowlist seeded from the portal plus known agency domains. The current `labels[-1] == cctld` rule must go — it passes `reddit.dk` and `wordpress.fr`.
- Keep the label heuristic only as a last-resort fallback for countries with no allowlist yet, and log loudly when it is used.

**(b) Page quality — a new admissibility filter, separate from `check_usable()`.**

Reject as evidence pages:
- path segments `/blog/`, `/news/`, `/press/`, `/features/`, `/speeches/`
- dated paths (`/2016/03/`, `/2023/12/`)
- non-content subdomains (`analytics.*`)
- known-dead shorteners (`go.usa.gov`, `1.usa.gov`) — retired in 2020, still all over Firecrawl's index
- the existing `_NON_PAGE_EXTENSIONS` from [usability.py:26](src/shared/tools/linkresolution/usability.py#L26)

Applied **per candidate**, never as a source-killer (see W3).

**Tests:** table-driven cases in a new `tests/unit/test_admissibility.py` covering every probe in the diagnosis — `analytics.usa.gov/x.csv`, `usa.gov/blog/2016/...`, `some-random-blog.dk`, `borger.dk`, `go.usa.gov/xUBA6/`.

**Size:** M. **Independent** — can start immediately.

---

### W3 — Search integration *(largest single win; no new vendor, no new spend)*

Firecrawl returns 10 ranked results with `url`, `title` **and** `description`. [search.py:210](src/shared/tools/linkresolution/sources/search.py#L210) keeps only the URL and the caller takes index 0.

1. **Keep the metadata.** Return `Candidate(url, title, snippet, position)` instead of a bare URL list.
2. **Return a ranked list, not one candidate.** `search_for_link()` yields N; `resolve_link()` ([chain.py:88-145](src/shared/tools/linkresolution/chain.py#L88-L145)) walks them applying W2 admissibility per candidate. **One CSV must not kill the source** — that alone caused 16 of the 21 `portal_default` fall-throughs.
3. **Score relevance before choosing.** Rank by overlap of the question's `title` + `what` against candidate title/snippet/URL path. Weight **URL-slug matches above snippet matches** — slugs are hard to game, verbose pages game snippets. Escalate to an LLM re-rank of the top 5 only when the best lexical score is below threshold.
4. **Drop the blanket `site:` prefix** ([search.py:265-271](src/shared/tools/linkresolution/sources/search.py#L265-L271)). Query naturally, then filter by domain. This is what separated `usaspending.gov/search` + `sam.gov/fpds` (unrestricted, correct) from CSV soup (`site:`-restricted).
5. **Never accept the bare portal root as evidence.** Treat a `portal_default` resolution as failure and force a retry.
6. **Fix the DDG short-circuit** ([search.py:295-303](src/shared/tools/linkresolution/sources/search.py#L295-L303)) — fall through to the remaining providers instead of returning early when nothing passes the domain filter.
7. **Drop the portal-boilerplate query wrapper** in the widened branch ([scheduler.py:352-358](src/orchestration/scheduler.py#L352-L358)). It biases the one path that can leave the portal straight back to the portal — the reason #321 still resolved to `usa.gov/` after escalating.

**Tests:** `test_resolver.py` — assert the ranker picks `usa.gov/health` over `usa.gov/` given recorded Firecrawl fixtures; assert a leading CSV candidate is skipped rather than collapsing the source.

**Size:** L. **Depends on:** W2(b) for the per-candidate filter.

---

### W4 — Escalation ladder *(wires W1 + W2 + W3 into the agreed policy)*

Replace the current binary strict/relaxed switch at [scheduler.py:320-329](src/orchestration/scheduler.py#L320-L329) with an explicit ladder:

| Round | Scope | Entry condition |
|---|---|---|
| 1 | Designated portal domain only | always |
| 2 | Portal sitemap (W5) | round 1 found nothing admissible |
| 3 | Designated-portal **allowlist** (see §3) | `never_found_relevant_page` from all agents |
| 4 | Any authoritative government domain (W2a) | `never_found_relevant_page` **and** locus is `any_government_domain` |

Round 4 stays closed for `national_portal_only` questions — widening those changes the score, not the accuracy.

Also: `resolved_url` is cleared in exactly one place, [scheduler.py:563](src/orchestration/scheduler.py#L563). Any new escalation step must clear it too, or it will silently re-assess the same page.

**Size:** M. **Depends on:** W1, W2, W3.

---

### W5 — Sitemap-first resolver

For `national_portal_only` questions, external search is the wrong tool. The portal's own sitemap is authoritative, free, and small — measured live:

| Portal | Sitemap | URLs |
|---|---|---|
| `usa.gov` | `/sitemap.xml` (urlset) | **1,531** |
| `borger.dk` | `/sitemap.xml` (urlset) | **1,979** |
| `india.gov.in` | `/sitemap.xml` (urlset) | 55 |
| `gov.uk` | `/sitemap.xml` (**index**) | 35 child sitemaps — expand one level |

`usa.gov/health` and `usa.gov/education` — the two pages whose absence produced the #095 and #103 false negatives — are both in that 1,531-URL list.

- New `portal_sitemap` source in `linkresolution/sources/`, ordered **ahead of** `search` for portal-only questions; add to `resolution_order` ([settings.py:115-123](src/shared/config/settings.py#L115-L123)).
- One fetch per portal per run, cached. Expand sitemap-index files one level.
- Rank with the **same scorer** built in W3 — the slug carries most of the signal.
- Fallback for portals with no sitemap: bounded BFS from the homepage (depth 2, ≤300 pages), cached identically.

**Size:** M. **Depends on:** W3 (shared scorer). High value, low risk.

---

### W6 — Page comprehension

1. **Paginated indexes.** `usa.gov/agency-index` server-renders only the "A" entries — "Department of Education" and "EPA" are not in that HTML at all; they live at `/agency-index/e`. Detect A–Z or numbered pagination and follow the shard matching the question's key term. **Recovers #011, #103, #161, #337 on its own.**
2. **Replace the flat 15k truncation** at [profiles.py:275](src/shared/prompts/profiles.py#L275) with relevance-windowed extraction — chunk the page, keep chunks matching the question's key terms, and state explicitly in the prompt when content was omitted.
3. **Let one-hop navigation cross domains** when the escalation ladder has reached round 4. [`_extract_same_domain_links()`](src/agents/assessor/agent.py#L293-L330) currently strips every off-domain link, so a `usa.gov` → `irs.gov` handoff is invisible to the model even when it is the obvious next step.

**Size:** M. **Independent** of W1–W5.

---

### W7 — Provider swap *(do last)*

Firecrawl is **not** the bottleneck — its unrestricted results are excellent. Swapping vendors while keeping take-first-result changes nothing. Do this after W3 so the comparison is meaningful.

1. Extract a thin `SearchProvider` interface — `search(query, limit) -> list[Candidate]`.
2. Implement `SerperProvider`; keep Firecrawl (upgraded `/v1` → `/v2`) as fallback; demote DDG/Bing HTML scraping to last resort.
3. Add `AIQ_SEARCH_PROVIDER` and `SERPER_API_KEY` to `Settings` and `_ENV_MAP` ([settings.py:112](src/shared/config/settings.py#L112), [settings.py:187](src/shared/config/settings.py#L187)) — mirror the existing `firecrawl_api_key` wiring.
4. Run the golden set against **each** provider and pick on measured precision, not vendor marketing.

**Why Serper if the numbers hold:** native Google `site:` is the operator failing on Firecrawl; returns `title`/`link`/`snippet`/`position`; **$0.30–$1 per 1k vs $5** for Brave or Google CSE (a full 193-country × 50-question cycle: ~$6–19 vs ~$96); 2,500 free credits cover the whole evaluation before committing.

**Do not adopt Google Custom Search JSON API** — closed to new customers since 2025, fully retired 1 Jan 2027.

**Size:** M.

---

### W0 — Measurement harness *(do first)*

Without this, every phase below is unfalsifiable and the four flat 8–11 Yes runs repeat.

- **Golden set:** ~25 of the 50 USA indicators, hand-labelled with correct evidence URL and expected Yes/No. ~20 are already validated in the diagnosis report.
- **Candidate capture:** persist the *full* ranked candidate list (url + title + snippet + source + score) into `units.data.resolution_history`, not just the chosen one. Today there is no way to ask "was the right link at position 3?"
- **Baseline recorded:** 42% `portal_default`, 100% single-domain fetches, 10/50 Yes, 48/50 zero-retry, 1/50 ever widened.

**Size:** S.

---

## 3. Open decisions — need a human call, not an engineering one

**35 of 50 questions are tagged `national_portal_only`.** I checked whether those tags contradict their own question text: **0 of 35 do.** The tagging is internally consistent, so this is not a data bug.

But the source wording underneath is ambiguous. All of them carry the same boilerplate:

> `criteria_for_yes`: "Evidence found on **the designated government portal** satisfying the What specification."

"The designated government portal" for a visa application is arguably `travel.state.gov`; for open datasets, `data.gov`. The compile-to-locus step resolved that ambiguity toward the strictest possible reading — a single domain.

**Recommendation:** define a **designated-portal allowlist per country** on `TargetPortal` ([entities.py:220-230](src/shared/state/entities.py#L220-L230)) — `usa.gov` + `data.gov` + `regulations.gov` + `usaspending.gov` + `travel.state.gov` — rather than letting a retry quietly widen the scope. Preserves scoring integrity, unblocks the questions, stays a deliberate decision.

**This decision gates the achievable score.** If 35/50 questions structurally cannot be answered from `usa.gov` alone, no amount of retrieval work will lift the result. Settle it before judging any re-run.

---

## 4. Sequencing

```
W0 (harness) ─┬─> W2 (admissibility) ─┬─> W3 (integration) ─> W5 (sitemap) ─┐
              │                       │                                      ├─> W4 (ladder) ─> re-run
              ├─> W1 (signal) ────────┘                                      │
              └─> W6 (comprehension) ──────────────────────────────────────┘
                                                                              └─> W7 (provider) ─> re-run
```

Measurement gate after **W3**, after **W5**, and after **W7**. Re-running the golden set at each gate is what turns this into a measurable progression.

**W1, W2, W3, W5 and W6 need no new vendor, no new key and no new spend — and on the evidence they carry most of the win.**

---

## 5. Success criteria

| Metric | Baseline (v4) | Target |
|---|---|---|
| Golden-set resolution precision@1 | not measured | **> 70%** |
| Units resolving to `portal_default` | 42% (21/50) | **< 10%** |
| Units that ever widened past the portal | 2% (1/50) | 20–40% |
| Fetches on a single domain | 100% | < 75% |
| Blog / dated / analytics URLs accepted as evidence | ≥ 2 observed | **0** |
| USA Yes count | 10/50 | 25–35/50 |
| Search cost per 50-question run | Firecrawl credits | < $0.15 |

Precision@1 on the golden set is the metric that matters. **The Yes count is a sanity check, not a target** — #336, #055 and #062/#063 are correctly "No" and must stay that way. A run that hits 40/50 Yes is a regression, not a win.

---

## 6. Risks

- **Ranking gamed by verbose pages** → weight URL-slug matches above snippet matches.
- **Dropping `site:` widens the candidate pool**, making W2 admissibility and `evidence_permitted()` ([locus.py](src/shared/tools/linkresolution/locus.py)) the only guard against off-portal evidence. That check already exists and runs at delivery — keep it, and test it.
- **Sitemaps go stale** or omit dynamic service pages → sitemap-first, search-second ordering means search still runs when the sitemap yields nothing above threshold.
- **Serper is an unofficial Google proxy** — ToS and availability risk is real. The `SearchProvider` interface in W7 is what makes that cheap to reverse.
- **W1 shifts the escalation rate.** A model that over-reports `never_found_relevant_page` will trigger escalation everywhere and multiply cost. Cap at `MAX_LINK_RETRIES = 3` (already in place) and watch the widen-rate metric.
