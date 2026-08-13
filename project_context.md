# UN E-Government Assessment Platform Automation - Project Context

## Meeting Purpose
To scope a project for automating and improving the UN's e-government assessment platform.

## Key Takeaways
- **Project Goal:** Automate the manual e-government assessment process for 193 countries and rebuild the public-facing knowledge base.
- **Core Challenge:** The assessment relies on human volunteers for subjective analysis and secure logins (e.g., Turkey's e-Devlet), making full automation impossible.
- **Proposed Solution:** Build an "agentic system" to pre-fill objective answers, allowing human assessors to focus on validation and complex features.
- **Key Constraint:** The project must be delivered as a consultant-led effort (not a vendor contract) to bypass UN procurement bureaucracy and ensure direct control over the team.

## Topics

### The UN E-Government Development Index (e-GDI)
- **Purpose:** Measures e-government maturity across 193 UN member states.
- **Components:** A composite index with three equal parts (1/3 each):
  - **Online Service Index (OSI):** Assesses the national portal via ~200 binary features.
  - **Telecommunication Infrastructure:** Data from other UN agencies (e.g., ITU).
  - **Human Capital:** Proxy indicators like adult literacy (from UNESCO).
- **Methodology:**
  - Two in-country volunteers conduct blind assessments using a questionnaire.
  - A reviewer resolves discrepancies; high-discrepancy results are sent back for a joint review.
  - The final data is manually imported into the public-facing platform.

### Assessment Process & Data Challenges
- **Manual Workflow:** The current process is highly manual, using Google Spreadsheets for assessments and scripts for discrepancy analysis.
- **Data Complexity:**
  - **Feature Evolution:** Assessment features change with each biennial edition (~50% difference over 8 years), making historical data mapping difficult.
  - **MSQ Data:** Member State Questionnaires (MSQs) provide rich government-reported data, but it is not used for rankings to maintain objectivity.
- **Project Scope:** The new platform must support multiple project types:
  - Biennial national e-government surveys.
  - Local Online Service Index (LOSI) for cities.
  - Custom assessments (e.g., UK cities).

### Proposed Solution: Automation & Platform Rebuild
- **Automation Strategy:**
  - An "agentic system" can analyze public portal content to pre-fill objective answers.
  - This provides a "human in the loop" workflow where assessors validate AI suggestions, saving significant time.
- **Platform Rebuild Goal:** Replace the problematic .NET Nuke backend with a robust, integrated system.
- **Requirements:**
  - Project management for surveys.
  - Role-based access (admin, reviewer, assessor).
  - Automated discrepancy detection with a configurable threshold (e.g., 5%).
  - Seamless data publication to the public frontend.

### Project Constraints & Path Forward
- **Procurement:** A direct vendor contract is unlikely due to UN bureaucracy. The preferred path is hiring individuals as consultants to ensure direct team control.
- **Hosting:** The platform must be compatible with UN infrastructure (currently Drupal) and support long-term hosting pre-payment, as recurring credit card payments are not feasible.
- **Budget:** A multi-year budget is available for the project.
- **Proof of Concept (PoC):** A low-effort PoC was suggested to demonstrate AI capabilities.
  - **Method:** Use the public "National E-government Toolkits" to generate assessment indicators.
  - **Test:** Run the AI against portals from diverse countries (USA, France, Brazil, China, Nigeria) and compare results to the public data.
