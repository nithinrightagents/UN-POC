# UN Project Scope Meeting: EGKB Modernization & AI Integration
**Date:** August 03  
**Duration:** 52 minutes  
**Participants:** 
- **Deniz Susar** – United Nations Department of Economic and Social Affairs (UN DESA)
- **Satheesh** – Technical Partner / Data Science Lead
- **Gokhan E.** – Technical Partner / Project Lead

---

## Context & Executive Summary

This meeting focused on defining the project scope for updating and modernizing the **United Nations E-Government Knowledge Base (EGKB)** and its underlying evaluation workflows. The EGKB assesses the digital government capabilities of **193 UN Member States** and selected cities worldwide.

### Core Objectives:
1. **Assessment Platform Modernization:** Overhaul the data collection, review, and publication platform used by UN staff, national assessors, and external reviewers.
2. **AI & Automation Integration:** Implement agentic AI tools to automatically assess standard, publicly verifiable portal features (e.g., W3C compliance, site maps, e-participation policies, security standards), pre-populating surveys to reduce manual volunteer workload while maintaining human-in-the-loop (HITL) oversight.
3. **Local Online Service Index (LOSI) Expansion:** Support city-level assessments beyond the primary national capitals/populous cities for custom regional projects (e.g., UK, Greece, Argentina).
4. **UN Operational & Administrative Compliance:** Ensure all proposed technical solutions align with strict UN procurement rules, hosting policies (prepaid/long-term enterprise hosting), and data security frameworks.

---

## Detailed Compacted Transcript

### Section 1: EGKB Overview & EGDI Index Architecture

**Deniz Susar:**
The project involves updating the United Nations E-Government Knowledge Base (EGKB) and improving its assessment infrastructure. The EGKB evaluates 193 UN Member States by analyzing their official national government portals (such as `usa.gov` or `turkiye.gov.tr`) across approximately 200 distinct features and indicators.

The overarching metric is the **E-Government Development Index (EGDI)**, which consists of three equally weighted sub-components (one-third each):

1. **Online Service Index (OSI):** Evaluates the presence and quality of online government services, portal content, institutional frameworks, technology, and e-participation mechanisms.
2. **Telecommunication Infrastructure Index (TII):** Evaluates national connectivity metrics, including percentage of internet users, mobile broadband subscriptions, mobile cellular subscriptions, and overall service affordability. (Data sourced directly from external UN agencies like the International Telecommunication Union - ITU).
3. **Human Capital Index (HCI):** Evaluates literacy and education metrics, such as adult literacy rates, combined primary/secondary/tertiary enrollment, and e-government literacy. (Data sourced from UNESCO and internal UN statistics).

While TII and HCI rely on secondary statistical data provided by other UN agencies, the **Online Service Index (OSI)** is produced directly by UN DESA through primary evaluation of national government portals.

---

### Section 2: Online Service Index (OSI) Assessment Methodology

**Deniz Susar:**
To produce the OSI, we evaluate national portals against standardized subcategories listed in the National E-Government Toolkit, including:
- **Institutional Framework:** Legal and policy framework regulating e-government and e-participation.
- **Service Provision:** Direct availability of transactional online services (e.g., permits, utility payments, civil registry).
- **Content & Technology:** Search functionality, help/FAQ sections, sitemaps, mobile responsiveness, accessibility, and W3C compliance.
- **E-Participation:** Tools and channels for public engagement, open data, and civic consultation.

#### Assessor Workflow & Discrepancy Resolution:
1. **Recruitment:** For each country, the UN recruits at least two local independent assessors who reside in that nation.
2. **Blind Assessment:** Assessors independently navigate the country's main portal (e.g., `eAlbania.al`) and complete a binary questionnaire (1 = Feature Exists, 0 = Feature Absent or Not Easily Findable).
3. **Findability Principle:** If a feature exists but cannot be located within a reasonable search time frame, assessors mark it as `0`. Findability is considered as critical as presence.
4. **Discrepancy Threshold:** Submissions from Assessor A and Assessor B are cross-referenced by a UN Reviewer. If discrepancies exceed 5%, the system alerts the reviewer. The survey is sent back to the assessors to meet, reconcile differences, and provide a unified final submission.
5. **Senior Review & Publication:** Reconciled data moves to a Senior Reviewer before final publication to the EGKB public interface.

---

### Section 3: Member State Questionnaire (MSQ) & Background Context

**Deniz Susar:**
Prior to launching the primary portal assessment, the UN sends a **Member State Questionnaire (MSQ)** directly to national government officials (e.g., Vice Governors or IT Ministry Directors responsible for e-government).

- **Contents:** The MSQ collects primary contact details, official URLs for specialized sub-portals (e-services, e-participation, open data, public procurement), and high-level national policy updates across 50+ pages.
- **Role in Assessment:** MSQ responses do **not** directly influence country rankings or scores, maintaining objective third-party evaluation. However, completed MSQs are provided to local assessors as contextual guidance during their evaluations.

---

### Section 4: Local Online Service Index (LOSI) for Cities

**Deniz Susar:**
In addition to national evaluations, the UN produces the **Local Online Service Index (LOSI)** focusing on major municipal portals.

- **Scope:** Evaluates the most populous city in each country (e.g., Madrid, Tallinn, Riyadh) across approximately 100 city-specific indicators (e.g., parking ticket payment, tourist applications, building permits).
- **Key Difference:** City-level assessments evaluate **only** online service provision (LOSI). Disaggregated infrastructure (TII) and human capital (HCI) metrics do not exist at the municipal level, so overall city rankings depend entirely on LOSI scores.
- **Custom City Projects:** The platform must support dynamic creation of localized project instances (e.g., `LOSI 2025 UK` evaluating 8 UK cities, or custom city projects in Greece and Argentina) allowing custom unit-of-study definitions and assigned volunteer assessors.

---

### Section 5: AI Integration, Pre-Population & System Architecture

**Satheesh:**
Our team can design an agentic AI architecture capable of autonomously inspecting public country portals against the standardized 200 indicators.

#### Proposed AI Capabilities:
1. **Automated Verification:** AI agents can scan portals for verifiable features (W3C compliance, security protocols, sitemaps, social media links, help sections, published policies).
2. **Pre-Populating Surveys:** Prior to human assessment, AI can run pre-evaluations and pre-fill survey responses with supporting evidence URLs and screenshots.
3. **Human-in-the-Loop (HITL):** Human assessors review, verify, or override pre-filled AI responses. This is essential for features behind login walls (e.g., national eID systems like Turkey's *E-Devlet*) or complex interactive flows.
4. **Historical Comparison:** AI can reference prior cycle evaluations (e.g., positive 2024 results) to highlight unchanged baseline features for quick human re-verification.

**Deniz Susar:**
Features and questions evolve significantly—roughly 50% of features change over multi-year cycles (e.g., 2018 vs. 2024 vs. 2026). The system must allow administrators to dynamically retire, modify, or add new indicators per project cycle.

---

### Section 6: UN Procurement, Hosting & Operational Constraints

**Deniz Susar:**
Working within the UN framework entails strict administrative constraints that influence technical design:

1. **Procurement Routes:** Formal institutional vendor bidding via central procurement is lengthy and unpredictable. Engaging technical experts as individual UN consultants offers a far more direct and controllable path.
2. **Hosting Requirements:** The UN cannot process recurring monthly credit card charges (e.g., $20–$30/month SaaS billing). All hosting must either fit directly within the UN enterprise infrastructure (e.g., .NET / Drupal enterprise environments) or be pre-funded and prepaid for 3–4 years as part of the initial agreement.
3. **Data Security & Residency:** Strict UN policies apply to data collection, staging, and user access management across public frontends and administrative backends.
4. **Travel & Bureaucracy Rules:** Official UN travel support for technical briefings or workshops is bound by strict nationality/passport guidelines (primarily supporting developing nation passport holders).

---

### Section 7: Next Steps & Action Plan

**Gokhan E. & Satheesh:**
To demonstrate capability without compromising UN data protocols:

1. **Proof of Concept (PoC) Development:**
   - Extract public indicators from the National E-Government Toolkit.
   - Select 5 diverse test country portals representing different languages and regions (e.g., USA [English], France [French], Brazil [Portuguese], China [Chinese], and a selected African nation).
   - Execute an AI-driven automated evaluation script against these portals.
   - Compare AI-generated scores against published historical benchmark scores (e.g., verifying if Iceland's AI-evaluated OSI aligns with its ~0.90 baseline score).
2. **Design Specification Review:** Review internal UN design documents to ensure frontend and backend compatibility.
3. **Follow-Up:** Convene for subsequent scoping once UN internal administrative milestones are confirmed.
