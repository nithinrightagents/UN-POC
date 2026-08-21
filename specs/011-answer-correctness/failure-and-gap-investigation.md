# 011 Gap Investigation & Web Verification Report

**Evaluation Session:** `bm-sess-6bc586ac55e8`  
**Dataset:** 25 USA Indicators (`bm-reference-links-us`)  
**Scope:** In-depth investigation of all 11 questions where the pipeline produced `no_suggestion` (withheld) or delivered `False` when the ground truth was `True`.

---

## 1. Summary Matrix of Gaps & Web Discoveries

| # | Question ID | Indicator Title | Delivered / State | Expected | Landed URL (Pipeline) | Authoritative Live Web URL | Root Cause of Agent Failure |
|---|---|---|---|---|---|---|---|
| **1** | **CP-030** | Procurement Results & Contract Awards | `False` (delivered) | `True` | `https://sam.gov/fpds` | `https://www.usaspending.gov/search` & `https://sam.gov` | Landed on deprecated FPDS redirect stub; search did not prioritize the primary `usaspending.gov/search` UI. |
| **2** | **EGL-036b** | Physical Spaces for Online Services (Libraries) | `False` (delivered) | `True` | `https://www.usa.gov/libraries` | `https://www.usa.gov/libraries` | Landed on correct page, but validator demanded explicit phrase "access online government services" rather than inferring public internet terminals. |
| **3** | **EGL-321** | Co-creation of e-Services — ENVIRONMENT | `WITHHELD` (`no_suggestion`) | `True` | `https://www.epa.gov/citizen-science` | `https://www.citizenscience.gov` & `https://www.challenge.gov` | Landed on EPA participatory science. Assessor said `True`, but validator rejected 3/3 arguing citizen data collection $\neq$ co-creation of e-services. |
| **4** | **EP-141** | Open Datasets — SOCIAL PROTECTION | `False` (delivered) | `True` | `https://catalog.data.gov/` | `https://catalog.data.gov/dataset?organization=social-security-administration` | Landed on Data.gov root rather than the SSA dataset sub-catalog. Root lacks inline dataset listings. |
| **5** | **EP-304** | Budget Expenditure Datasets — EDUCATION | `False` (delivered) | `True` | `https://fiscaldata.treasury.gov/americas-finance-guide/federal-spending/` | `https://www.usaspending.gov/agency/department-of-education` & `https://www.ed.gov/about/overview/budget` | Landed on general Treasury spending guide rather than the Department of Education specific budget portal. |
| **6** | **IF-011** | Names & Titles of Heads of Department | `WITHHELD` (`no_suggestion`) | `True` | `https://www.whitehouse.gov/administration/cabinet/` | `https://www.whitehouse.gov/administration/cabinet/` | **Landed on exact ground truth!** Assessor said `True` (95%), but page exceeded limit by 19.5k chars; validator failed to verify citation on truncated DOM. |
| **7** | **IF-338** | Legislation on Personal Data Protection | `False` (delivered) | `True` | `https://www.usa.gov/privacy` | `https://www.justice.gov/opcl` (Privacy Act of 1974, 5 U.S.C. 552a) | Sitemap lexical match picked USA.gov's internal website privacy policy rather than federal privacy legislation. |
| **8** | **IF-340** | Legislation & Policy on Cybersecurity | `WITHHELD` (`no_suggestion`) | `True` | `https://www.gsa.gov/technology/government-it-initiatives/cybersecurity/cybersecurity-programs-and-policy` | `https://www.cisa.gov` (FISMA 2014 & Binding Operational Directives) | Landed on GSA cybersecurity page. Assessor cited FISMA 2014 (`True`), but validator failed element reference extraction. |
| **9** | **SP-166** | Online Services Provision — ENVIRONMENT | `False` (delivered) | `True` | `https://www.epa.gov/home` | `https://echo.epa.gov` & `https://www.epa.gov/e-manifest` | Landed on EPA homepage/search hub rather than dedicated online service platforms (ECHO, e-Manifest, EJSCREEN). |
| **10** | **SP-166b** | SMS Alerts for Public Services — ENVIRONMENT | `False` (delivered) | `True` | `https://www.ready.gov/alerts` | `https://www.airnow.gov` & `https://www.enviroflash.info` | Landed on FEMA emergency alerts (`ready.gov`). `enviroflash.info` was filtered due to `.info` non-gov TLD. |
| **11** | **TECH-022** | Citizens Access to Own Personal Data / Digital ID | `False` (delivered) | `True` | `https://www.usa.gov/social-security-report-a-death` | `https://www.login.gov` & `https://www.ssa.gov/myaccount` | Sitemap lexical bias matched "Social Security" to `report-a-death` subpage instead of single sign-on / account portals. |

---

## 2. Detailed Failure Analysis & Live Web Investigation

---

### Case 1: CP-030 — Procurement Contract Awards & Results

*   **Question Summary:** Evidence of publicly available procurement contract awards and results.
*   **Pipeline Outcome:** Landed on `https://sam.gov/fpds` (Search). Delivered `False` (conf 40%).
*   **Ground Truth:** `https://www.usaspending.gov/search` (also accepts `https://sam.gov`).
*   **Live Web Verification:**
    *   **SAM.gov** has fully consolidated the Federal Procurement Data System (FPDS). The active portal for searching individual contract awards is `https://sam.gov/content/opportunities` and `https://sam.gov` (Contract Awards domain).
    *   **USAspending.gov** (`https://www.usaspending.gov/search`) provides advanced search for all federal procurement awards, outlays, and recipient award profiles.
*   **Why the Agent Failed:**
    1.  The search query returned `sam.gov/fpds`, which is an informational transition stub explaining the migration of FPDS to SAM.gov rather than the interactive search tool itself.
    2.  The assessor inspected the static text of `/fpds`, found no live award table on that page, and concluded `False`.

---

### Case 2: EGL-036b — Physical Spaces with Internet for Online Services

*   **Question Summary:** Evidence of access to physical spaces (libraries, post offices, schools) equipped with computers and internet to access online public services.
*   **Pipeline Outcome:** Landed on `https://www.usa.gov/libraries` (Search). Delivered `False` (conf 75%).
*   **Ground Truth:** `https://www.usa.gov/libraries`.
*   **Live Web Verification:**
    *   `https://www.usa.gov/libraries` is the official federal directory connecting citizens to local public libraries and state library agencies.
    *   According to the Institute of Museum and Library Services (IMLS) and Gates Foundation public access studies, U.S. public libraries provide free public computers and high-speed Wi-Fi expressly used to apply for government benefits (FEMA, Medicare, tax filing, job portals).
*   **Why the Agent Failed:**
    1.  The assessor initially said `True` based on library locator tools.
    2.  During validation retry, the validator demanded verbatim phrasing stating *"these computers are provided for online government services"*. Because the text described general library locator services, the model revised its answer to `False`.

---

### Case 3: EGL-321 — Co-Creation of e-Services in Environment

*   **Question Summary:** Evidence of collaborating with the public to co-create, co-design, or co-produce online public services in Environment.
*   **Pipeline Outcome:** Landed on `https://www.epa.gov/citizen-science` (Search). **Withheld** (`insufficient_positions`).
*   **Ground Truth:** `https://www.citizenscience.gov` & `https://www.challenge.gov`.
*   **Live Web Verification:**
    *   **CitizenScience.gov** operates under the Crowdsourcing and Citizen Science Act of 2016 (15 U.S.C. 3724) as the official hub for crowdsourcing and citizen co-creation across federal agencies.
    *   **Challenge.gov** runs federal prize competitions inviting the public and developers to design tools, apps, and public services.
*   **Why the Agent Failed:**
    1.  The search engine landed on EPA's participatory science hub (`epa.gov/citizen-science`).
    2.  The assessor rated this `True` (conf 90-95%) citing public involvement in environmental data collection.
    3.  The validator strictly reasoned that *citizen science data collection* (e.g., measuring air particulate levels) does not equal *co-creation of government IT / e-services*. It rejected all 3 attempts with score 0.0, causing the unit to withhold.

---

### Case 4: EP-141 — Open Datasets in Social Protection

*   **Question Summary:** Evidence of open government dataset(s) on budget, expenditure, or programs in Social Protection.
*   **Pipeline Outcome:** Landed on `https://catalog.data.gov/` (Search). Delivered `False` (conf 90%).
*   **Ground Truth:** `https://catalog.data.gov/dataset?organization=social-security-administration` or `https://www.ssa.gov/open`.
*   **Live Web Verification:**
    *   **Data.gov** hosts thousands of datasets published by the Social Security Administration (OASDI Beneficiaries by State/County, SSI monthly statistics, Disability Claims data).
    *   **SSA Open Data** (`https://www.ssa.gov/open/data/`) provides direct public data feeds.
*   **Why the Agent Failed:**
    1.  Search query `"Data.gov social protection datasets"` collapsed onto the catalog root `https://catalog.data.gov/`.
    2.  The catalog homepage displays high-level counts and search boxes but no specific dataset records inline.
    3.  The assessor read the root page, saw general stats, and answered `False`.

---

### Case 5: EP-304 — Budget Expenditure Datasets in Education

*   **Question Summary:** Evidence of open dataset(s) on budget/expenditure in Education (CSV, JSON, PDF).
*   **Pipeline Outcome:** Landed on `https://fiscaldata.treasury.gov/americas-finance-guide/federal-spending/` (Search). Delivered `False` (conf 95%).
*   **Ground Truth:** `https://www.usaspending.gov` or `https://www.ed.gov/about/overview/budget`.
*   **Live Web Verification:**
    *   **USAspending.gov** (`https://www.usaspending.gov/agency/department-of-education`) publishes full downloadable datasets (Files A–F, JSON/CSV) of education obligations and outlays.
    *   **ED.gov** (`https://www.ed.gov/about/overview/budget/budget-history`) publishes annual budget appropriations tables and Congressional justifications in Excel/CSV/PDF formats.
*   **Why the Agent Failed:**
    1.  The search landed on the Treasury's general *America's Finance Guide* explaining overall federal outlays.
    2.  The assessor correctly noted that the general Treasury page did not contain Education-specific budget datasets, answering `False`.

---

### Case 6: IF-011 — Names and Titles of Heads of Department

*   **Question Summary:** A section, chart, or webpage displaying names and official titles of heads of government departments/ministries.
*   **Pipeline Outcome:** Landed on `https://www.whitehouse.gov/administration/cabinet/` (Search). **Withheld** (`insufficient_positions`).
*   **Ground Truth:** `https://www.whitehouse.gov/administration/cabinet/` (Exact Match).
*   **Live Web Verification:**
    *   `https://www.whitehouse.gov/administration/cabinet/` is the official Cabinet directory listing all 15 executive department secretaries (State, Treasury, Defense, etc.) with official titles and profiles.
*   **Why the Agent Failed:**
    1.  Link resolution was **100% accurate** and landed on the exact reference page.
    2.  The assessor correctly answered `True` (95%) and quoted department secretaries.
    3.  **The Failure Mechanism:** The White House Cabinet page is large (exceeded the 15,000 character limit by 19,539 characters). When the validator ran its automated verification check, it failed to resolve the exact DOM element citation on the truncated representation, issuing a quality score of 0.0 (`required evidence component missing`). After 3 retries, the prefill was withheld.

---

### Case 7: IF-338 — Legislation on Personal Data Protection

*   **Question Summary:** Evidence of national legislation/statute safeguarding personal data and privacy.
*   **Pipeline Outcome:** Landed on `https://www.usa.gov/privacy` (Sitemap). Delivered `False` (conf 40%).
*   **Ground Truth:** `https://www.justice.gov/opcl` (Privacy Act of 1974, 5 U.S.C. § 552a).
*   **Live Web Verification:**
    *   The primary U.S. federal statute governing personal data protection is the **Privacy Act of 1974 (5 U.S.C. 552a)**, overseen by the Department of Justice Office of Privacy and Civil Liberties (OPCL) at `https://www.justice.gov/opcl`.
    *   Sectoral data privacy laws include HIPAA (`hhs.gov/hipaa`) and the FTC Act (`ftc.gov`).
*   **Why the Agent Failed:**
    1.  Sitemap lexical matching matched `"privacy"` to `https://www.usa.gov/privacy`.
    2.  `usa.gov/privacy` is USA.gov's internal website cookie and notice policy, not federal legislation.
    3.  The assessor accurately recognized that a website privacy policy is not national legislation and answered `False`.

---

### Case 8: IF-340 — Legislation & Policy on Cybersecurity

*   **Question Summary:** Evidence of national legislation, law, policy, or regulation on cybersecurity.
*   **Pipeline Outcome:** Landed on `https://www.gsa.gov/technology/government-it-initiatives/cybersecurity/cybersecurity-programs-and-policy` (Search). **Withheld** (`insufficient_positions`).
*   **Ground Truth:** `https://www.cisa.gov` (FISMA 2014, CISA Binding Operational Directives).
*   **Live Web Verification:**
    *   The **Federal Information Security Modernization Act of 2014 (FISMA)** (44 U.S.C. § 3551 et seq.) is the foundational cybersecurity statute, codified at CISA (`cisa.gov`) and GSA (`gsa.gov`).
*   **Why the Agent Failed:**
    1.  Landed on GSA's official Cybersecurity Programs & Policy page.
    2.  The assessor answered `True` (conf 100%) and explicitly cited FISMA 2014.
    3.  The validator failed the run on element citation extraction (`quality_score=0.0`), leading to 3 failed retries and withholding the prefill.

---

### Case 9: SP-166 — Online Services Provision in Environment

*   **Question Summary:** Evidence of online service provision listed for Environment (e.g., permitting, reporting, compliance).
*   **Pipeline Outcome:** Landed on `https://www.epa.gov/home` (Search). Delivered `False` (conf 40%).
*   **Ground Truth:** `https://www.epa.gov` / `https://echo.epa.gov` / `https://www.epa.gov/e-manifest`.
*   **Live Web Verification:**
    *   The EPA operates major public online transactional services:
        *   **ECHO** (`https://echo.epa.gov`): Public compliance and enforcement search.
        *   **e-Manifest** (`https://www.epa.gov/e-manifest`): Hazardous waste electronic tracking and reporting.
        *   **EJSCREEN** (`https://ejscreen.epa.gov`): Environmental justice mapping tool.
*   **Why the Agent Failed:**
    1.  The search query landed on `https://www.epa.gov/home` (homepage).
    2.  The assessor read the homepage overview, found general topics and local search widgets, but found no explicit consolidated catalog titled "Online Services", answering `False`.

---

### Case 10: SP-166b — SMS Alerts in Environment

*   **Question Summary:** Evidence of users' ability to receive SMS/text alerts for services in Environment (e.g., air quality alerts).
*   **Pipeline Outcome:** Landed on `https://www.ready.gov/alerts` (Search). Delivered `False` (conf 75%).
*   **Ground Truth:** `https://www.enviroflash.info` or `https://www.airnow.gov`.
*   **Live Web Verification:**
    *   **EnviroFlash** (`https://www.enviroflash.info`): EPA automated system sending air quality forecasts and smog alerts via SMS and email.
    *   **AirNow.gov** (`https://www.airnow.gov`): Official EPA air quality app with real-time push/SMS notifications.
*   **Why the Agent Failed:**
    1.  `enviroflash.info` uses the `.info` TLD. The pipeline's government domain filter (`is_government_domain`) strictly rejects non-`.gov`/`.mil` domains for safety.
    2.  Search escalated to FEMA's `ready.gov/alerts`, which covers generic disasters rather than environmental air quality alerts. The assessor accurately answered `False` on the FEMA page.

---

### Case 11: TECH-022 — Citizen Access to Own Personal Data / Digital ID

*   **Question Summary:** Ability for users to access their own government-held data (Social Security records, taxes, personal file) with authentication.
*   **Pipeline Outcome:** Landed on `https://www.usa.gov/social-security-report-a-death` (Sitemap). Delivered `False` (conf 40%).
*   **Ground Truth:** `https://www.login.gov` & `https://www.ssa.gov/myaccount`.
*   **Live Web Verification:**
    *   **Login.gov** (`https://www.login.gov`) is the U.S. government's centralized digital identity service.
    *   **SSA myAccount** (`https://www.ssa.gov/myaccount/`) allows citizens to log in, view lifetime earnings records, benefit statements, and personal data.
    *   **IRS Online Account** (`https://www.irs.gov/payments/your-online-account`) provides tax account transcripts.
*   **Why the Agent Failed:**
    1.  Sitemap lexical matching matched the query term `"Social Security"` against `usa.gov/social-security-report-a-death`.
    2.  The page explains how to notify SSA of a death, not how living citizens access their personal records.
    3.  The assessor accurately recognized that reporting a death does not provide access to one's own data and answered `False`.

---

## 3. Taxonomy of Failure Modes

Across the 11 gaps, failures fall into three clear architectural categories:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        11 FAILURE CASES BREAKDOWN                      │
├────────────────────────┬───────────────────────┬───────────────────────┤
│ Link Resolution Bias   │ DOM / Validator Gate  │ Domain Whitelist /    │
│ & Shallow Navigation   │ & Truncation          │ Evaluation Nuance     │
│ (6 cases)              │ (3 cases)             │ (2 cases)             │
├────────────────────────┼───────────────────────┼───────────────────────┤
│ • CP-030 (FPDS vs Search)│ • IF-011 (White House)│ • SP-166b (.info TLD) │
│ • EP-141 (Data.gov root) │ • IF-340 (GSA FISMA)  │ • EGL-036b (Strict    │
│ • EP-304 (Treasury guide)│ • EGL-321 (Validator  │   library wording)    │
│ • IF-338 (Site privacy)  │   concept mismatch)   │                       │
│ • SP-166 (EPA root)      │                       │                       │
│ • TECH-022 (Death report)│                       │                       │
└────────────────────────┴───────────────────────┴───────────────────────┘
```

---

## 4. Key Actionable Recommendations

1.  **Search Query Specificity for Datasets & Services:**
    *   When searching for open datasets (EP-141, EP-304), append `organization` or `dataset search` to queries so search engines return dataset catalog landing pages rather than root domains (`catalog.data.gov/dataset?...` vs `catalog.data.gov`).
2.  **Sitemap Candidate Quality Filter:**
    *   Exclude generic metadata pages (`/privacy`, `/accessibility`, `/report-a-death`) from winning sitemap rankings when the indicator explicitly seeks national statutory laws or authentication services.
3.  **Validator Truncation & Citation Resilience:**
    *   For pages exceeding 15k characters (e.g. `whitehouse.gov/administration/cabinet`), ensure the validator receives the chunk containing the assessor's citation or relaxes strict CSS selector extraction when the text quote is verifiably present.
4.  **Accepted Alternatives for Agency Cross-Domain Services:**
    *   Add `https://www.airnow.gov` to `SP-166b` accepted alternatives and query variants so it resolves on `.gov` without hitting `.info` filters.
