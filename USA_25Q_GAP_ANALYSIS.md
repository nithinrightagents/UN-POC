# USA 25-Question Run: Agent Pipeline vs. Antigravity Web Search Gap Analysis

**Date:** 2026-08-21  
**Target Portal:** `https://www.usa.gov` (United States)  
**Sample:** 25-question random sample (Seed: 42) from UN OSI 2024 Relaxed Questionnaire  
**Screenshot Status:** **Fully removed** (0 captures generated)

---

## 1. Executive Summary

| Category | Count | Percentage | Details |
|---|---|---|---|
| **Delivered YES** | 7 | 28% | #003 (Search), #015 (Language), #043 (Taxes), #048 (Address change), #095 (Health), #108 (Education), #340 (Cybersecurity) |
| **Delivered NO** | 15 | 60% | #011, #022/#024, #030, #036b, #062/#063, #108a, #137b, #141, #170, #173, #304, #321, #336, #337, #338 |
| **No Suggestion (Validation / Outage Drop)** | 3 | 12% | #124 (Employment), #166 (Environment), #166b (Environment Alerts) |
| **Total Evaluated** | **25** | **100%** | **18 questions resolved to NO / NOT FOUND / NO SUGGESTION** |

---

## 2. Comparison Matrix: Pipeline vs. Antigravity Ground Truth

Below is the comparative breakdown of all **18 questions** that resolved to **NO / NOT FOUND / NO SUGGESTION**:

| # | Indicator / Question | Locus | Pipeline Resolved URL | Pipeline Answer & Reasoning | Antigravity Real-World Finding | Verdict |
|---|---|---|---|---|---|---|
| **#030** | Procurement results | `any_gov_domain` | `https://sam.gov/fpds` | **NO** (Page is an interactive search widget without pre-rendered award rows) | **`https://www.usaspending.gov/search`** and **`sam.gov`** publish all federal contract awards and procurement results. | **False Negative** (Search selected un-rendered widget instead of USAspending) |
| **#338** | Personal data protection legislation | `national_portal_only` | `https://www.usa.gov/privacy` | **NO** (Only discusses website cookies and portal privacy policy) | **Privacy Act of 1974** (5 U.S.C. § 552a) & `justice.gov/opcl`. `usa.gov/privacy` is only the site notice. | **False Negative** (Domain lock to `usa.gov` + superficial `/privacy` URL match) |
| **#137b** | SMS alerts: Social Protection | `national_portal_only` | `https://www.ready.gov/alerts` | **NO** (Only discusses FEMA emergency/weather alerts) | **SSA SMS notifications** exist via `ssa.gov` (opt-in updates & MFA), but not hosted on `usa.gov`. | **False Negative** (Wrong domain / FEMA fallback) |
| **#108a** | Mobile services: Education | `national_portal_only` | `https://www.usa.gov/education` | **NO** (No mobile app or mobile services mentioned on page) | **Retired in 2022**: Department of Education retired the `myStudentAid` app in favor of responsive web `StudentAid.gov`. | **True Negative** (No dedicated standalone mobile app exists) |
| **#124** | Online services: Employment | `national_portal_only` | `https://www.usa.gov/jobs` | **NO SUGGESTION** (3 Assessor runs answered YES (90%), but Validator rejected header-only quotes) | **`https://www.usa.gov/jobs`** & **`usajobs.gov`** explicitly provide online unemployment and job search services. | **Pipeline Bug** (Validator rejected quote of heading without body text) |
| **#173** | Policies: Justice sector | `any_gov_domain` | `https://www.usa.gov/historical-documents` | **NO** (Historical documents page does not list current justice policies) | **`https://www.justice.gov/olp/policy-initiatives`** and `justice.gov/about/strategic-plan` detail national justice policies. | **False Negative** (Search resolved to irrelevant history page) |
| **#170** | Open datasets: Environment | `national_portal_only` | `https://open.gsa.gov/data/` | **NO** (GSA internal open gov page has no environmental datasets) | **`https://catalog.data.gov`** & **`https://www.epa.gov/data`** host thousands of open environmental datasets. | **False Negative** (Domain lock prevented reaching `data.gov`/`epa.gov`) |
| **#337** | National CIO or equivalent | `national_portal_only` | `https://www.usa.gov/agencies/chief-information-officers-council` | **NO** (Council directory lists agency contact info, not individual CIO name) | **`https://www.cio.gov`** & `whitehouse.gov/omb` name the Federal Chief Information Officer. | **False Negative** (Domain lock to `usa.gov` directory entry) |
| **#336** | Legislation against misinformation | `national_portal_only` | `https://www.usa.gov` | **NO** (No misinformation legal framework on portal) | **No US statute exists**: Broad misinformation bans are unconstitutional under the First Amendment (CRS reports). | **True Negative** (Factually absent in the US) |
| **#166** | Online services: Environment | `national_portal_only` | `https://www.state.gov/environment/` | **NO SUGGESTION** (State.gov returned 403 Forbidden; Assessor NO rejected by Validator) | **`https://www.epa.gov`** hosts ECHO, e-Manifest, e-permitting, and EJSCREEN. `usa.gov` has no environment section. | **Pipeline Bug** (Locus escalation hit 403 error page instead of `epa.gov`) |
| **#022,#024**| Citizen access to own data | `national_portal_only` | `https://www.usa.gov/accessibility` | **NO** (Page is Section 508 disability compliance, not personal data access) | **`https://www.login.gov`**, **`ssa.gov/myaccount`**, and **`irs.gov/payments/your-online-account`** provide full personal data access. | **False Negative** (Keyword confusion: accessibility vs data access) |
| **#321** | Co-creation: Environment | `any_gov_domain` | `https://19january2021snapshot.epa.gov/...` | **NO** (Frozen 2021 archive discusses inter-agency governance, not public co-creation) | **`https://www.citizenscience.gov`**, **`https://www.challenge.gov`**, and EPA Participatory Science engage public solvers. | **False Negative** (Search retrieved outdated snapshot archive) |
| **#062,#063**| Water / Electricity utility payments | `any_gov_domain` | `https://www.usa.gov/help-with-utility-bills` | **NO** (Only lists LIHEAP financial assistance, no payment portal) | **No national utility payment portal exists**: US utilities are strictly municipal, regional, or private. | **True Negative** (Factually absent at federal level) |
| **#141** | Open datasets: Social Protection | `national_portal_only` | `https://data.gov/open-gov/` | **NO** (Article on OPEN Government Data Act does not list datasets) | **`https://catalog.data.gov/dataset?organization=social-security-administration`** and `ssa.gov/open` have hundreds of datasets. | **False Negative** (Search hit general blog page instead of data catalog) |
| **#304** | Budget datasets: Education | `national_portal_only` | `https://www.usa.gov/education` | **NO** (Consumer education guide has no budget datasets) | **`https://www.usaspending.gov`**, `catalog.data.gov`, and `ed.gov/about/overview/budget` provide full datasets. | **False Negative** (Domain lock to `usa.gov` + consumer page selection) |
| **#166b**| SMS alerts: Environment | `national_portal_only` | `https://www.ready.gov/alerts` | **NO SUGGESTION** (Assessor cited heading; Validator rejected for lack of specific air/env alert text) | **`https://www.enviroflash.info`** & **`airnow.gov`** (EPA) provide automated air quality text alerts. | **Pipeline Bug** (Escalated to FEMA Ready.gov instead of EPA EnviroFlash) |
| **#011** | Names and titles of heads of department | `national_portal_only` | `https://www.usa.gov/agency-index` | **NO** (A-Z agency index lists websites and phone numbers, but omits leader names) | **`https://www.whitehouse.gov/administration/cabinet`** and `usa.gov/executive-departments` list all department heads. | **False Negative** (Judged against unpopulated agency index) |
| **#036b**| Physical spaces for online services | `national_portal_only` | `https://www.usa.gov/libraries` | **NO** (Public libraries provide general computer access, but Assessor wanted dedicated e-gov center) | **Public Libraries** (`imls.gov`, `careeronestop.org`) & **American Job Centers** (`dol.gov`) serve as official federal physical access points. | **Borderline/Methodology** (Assessor strictly required dedicated e-gov centers) |

---

## 3. Key Gaps & Root Cause Analysis

### A. The "Federal Architecture vs. `national_portal_only`" Dilemma (6 Questions)
* **The Gap:** 35 of the 50 indicators in the UN questionnaire are configured as `national_portal_only`. In centralized governments (e.g. Denmark's `borger.dk`), all services and datasets are cataloged on the central domain. In the US, `usa.gov` is a signposting directory; actual delivery is delegated to federated agency domains (`data.gov`, `usaspending.gov`, `cio.gov`, `justice.gov`, `whitehouse.gov`).
* **Impact:** The pipeline is forced to evaluate only `usa.gov`. When it hits high-level consumer guides (`usa.gov/education`, `open.gsa.gov`), it finds no technical data/leadership details and answers "NO".

### B. Semantic Search Mismatch & Archive Traps (5 Questions)
* **Keyword Misinterpretation:** Indicator `#022/#024` ("Accessibility to own data") matched `usa.gov/accessibility` based on the word "accessibility", which on US portals means Section 508 accessibility (screen readers/disabilities), not personal data access.
* **Archival URLs:** Indicator `#321` (Environmental co-creation) resolved to a frozen `19january2021snapshot.epa.gov` archive rather than live federal platforms (`citizenscience.gov` / `challenge.gov`).
* **Un-rendered Search Portals:** Indicator `#030` (Procurement) landed on `sam.gov/fpds`, a client-side search UI with no pre-rendered records, causing the model to conclude that awards were absent.

### C. Validation & Outage Terminal Drops (3 Questions)
* **Heading-Only Citations (#124):** All assessor runs accurately determined that `usa.gov/jobs` provides online employment services, but cited only the top section heading. The Validator rejected this as incomplete evidence, causing 3 failed retries and dropping a valid YES into `no_suggestion`.
* **403 Forbidden Errors (#166):** Off-portal escalation to `state.gov/environment/` was blocked by anti-bot protection. The pipeline attempted to assess the raw 403 error page rather than catching the HTTP error and trying the next search candidate (`epa.gov`).

### D. Verified True Negatives (3 Questions)
* **Factually Absent Services:** The pipeline correctly identified true negatives where US federal law or jurisdiction does not provide a national service:
  - `#336`: Broad misinformation bans do not exist due to First Amendment protections.
  - `#062/#063`: Residential water/electricity utility billing is municipal/private, not federal.
  - `#108a`: Federal education mobile apps were decommissioned in 2022.

---

## 4. Key Recommendations

1. **Multi-Domain Federal Alias:** For federated nations (US, Germany, Australia), allow `national_portal_only` to recognize authoritative national sub-portals (`data.gov`, `usaspending.gov`, `cio.gov`, `whitehouse.gov`, `login.gov`).
2. **Relevance Re-Ranking:** Rank top 10 search results using semantic similarity against the question's `title` and `what` criteria before applying domain filters to prevent keyword traps (like accessibility).
3. **Assessor Evidence Extraction:** Require the Assessor Agent to extract both section headers and at least one actionable sentence or link label to satisfy the Validator.
4. **HTTP Status & Anti-Bot Guardrails:** Treat 403/500 HTTP responses as crawler failures rather than assessable content, triggering an immediate fallback to Candidate #2.
