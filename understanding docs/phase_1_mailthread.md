FULL Mail thread phase 1 
his will give you more information, start with this first - confidential 

---------- Forwarded message ---------
From: G. Erkavun <gerkavun@gmail.com>
Date: Mon, Aug 3, 2026 at 6:51 PM
Subject: Re: UN Project Scope Discussion
To: Deniz Susar <deniz.susar@gmail.com>
Cc: satheesh <satheesh.nextgen@gmail.com>

Hi Deniz and Satheesh,

Thank you for both your time and the detailed explanation of the scope and the vision of the UN e-Government Knowledgebase Project

Please find below the recording and the summary of our meeting.

As the next step, Satheesh and I will discuss the project with our internal team and advise on a spec and a partial demo of what we can build to progress with this project.
This work can also be used as a presentation within a few months once there is more clarity about the next steps from UN.

In the meantime, we will be in touch with follow-up questions and feedback once we have progress with this initial demo plan.

Thank you again for your time and the opportunity.

Regards,
Gokhan
UN Project Scope Meeting - August 03

VIEW RECORDING - 52 mins (No highlights)
Meeting Purpose
To scope a project for automating and improving the UN's e-government assessment platform.
Key Takeaways
•	Project Goal: Automate the manual e-government assessment process for 193 countries and rebuild the public-facing knowledge base.
•	Core Challenge: The assessment relies on human volunteers for subjective analysis and secure logins (e.g., Turkey's e-Devlet), making full automation impossible.
•	Proposed Solution: Build an "agentic system" to pre-fill objective answers, allowing human assessors to focus on validation and complex features.
•	Key Constraint: The project must be delivered as a consultant-led effort (not a vendor contract) to bypass UN procurement bureaucracy and ensure direct control over the team.
Topics
The UN E-Government Development Index (e-GDI)
•	Purpose: Measures e-government maturity across 193 UN member states.
•	Components: A composite index with three equal parts (1/3 each):
o	Online Service Index (OSI): Assesses the national portal via ~200 binary features.
o	Telecommunication Infrastructure: Data from other UN agencies (e.g., ITU).
o	Human Capital: Proxy indicators like adult literacy (from UNESCO).
•	Methodology:
o	Two in-country volunteers conduct blind assessments using a questionnaire.
o	A reviewer resolves discrepancies; high-discrepancy results are sent back for a joint review.
o	The final data is manually imported into the public-facing platform.
Assessment Process & Data Challenges
•	Manual Workflow: The current process is highly manual, using Google Spreadsheets for assessments and scripts for discrepancy analysis.
•	Data Complexity:
o	Feature Evolution: Assessment features change with each biennial edition (~50% difference over 8 years), making historical data mapping difficult.
o	MSQ Data: Member State Questionnaires (MSQs) provide rich government-reported data, but it is not used for rankings to maintain objectivity.
•	Project Scope: The new platform must support multiple project types:
o	Biennial national e-government surveys.
o	Local Online Service Index (LOSI) for cities.
o	Custom assessments (e.g., UK cities).
Proposed Solution: Automation & Platform Rebuild
•	Automation Strategy:
o	An "agentic system" can analyze public portal content to pre-fill objective answers.
o	This provides a "human in the loop" workflow where assessors validate AI suggestions, saving significant time.
•	Platform Rebuild:
o	Goal: Replace the problematic .NET Nuke backend with a robust, integrated system.
o	Requirements:
	Project management for surveys.
	Role-based access (admin, reviewer, assessor).
	Automated discrepancy detection with a configurable threshold (e.g., 5%).
	Seamless data publication to the public frontend.
Project Constraints & Path Forward
•	Procurement: A direct vendor contract is unlikely due to UN bureaucracy. The preferred path is hiring individuals as consultants to ensure direct team control.
•	Hosting: The platform must be compatible with UN infrastructure (currently Drupal) and support long-term hosting pre-payment, as recurring credit card payments are not feasible.
•	Budget: A multi-year budget is available for the project.
•	Proof of Concept (PoC): A low-effort PoC was suggested to demonstrate AI capabilities.
o	Method: Use the public "National E-government Toolkits" to generate assessment indicators.
o	Test: Run the AI against portals from diverse countries (USA, France, Brazil, China, Nigeria) and compare results to the public data.
Next Steps
•	Satheesh & Gokhan:
o	Review meeting recording and shared documents to refine the project scope.
o	Evaluate the feasibility of building a low-effort AI PoC for a potential future presentation.
•	Deniz:
o	Provide the final design specifications when ready.
o	Inform Satheesh and Gokhan of any updates on the project's internal timeline.
Action Items
•	Email Deniz follow-up w/ recording + summary - WATCH (5 secs)


On Mon, Aug 3, 2026 at 11:56 AM Gokhan Erkavun <gerkavun@gmail.com> wrote:
Hi Deniz,

Thank you for the quick turnaround and sending responses.


Looking forward to discuss further later today.

Regards,
Gokhan


On Aug 3, 2026, at 11:33 AM, Deniz Susar <deniz.susar@gmail.com> wrote:

Yes, we can discuss at 5pm. Pls see responses in bold (DS:) below:

A few things I'd want Deniz to clarify Monday so we scope this tightly:

  - Are we doing just the design package and mock-up, or the build too?
DS: Nothing yet, but it makes sense to look at design and adjust as you see fit before implementation
  - Is the AI scope (website scanning, cross-source checks, anomaly flags) firm or aspirational?
DS: We are flexible. 
  - Are survey responses all in English, or multiple languages? That changes the AI effort a lot.
DS: The websites are in different languages. The responses of assessors are in English.
  - How many past cycles of Google Sheets data exist to migrate?
DS: Approximately 4-5 surveys. 

On Mon, Aug 3, 2026 at 11:04 AM Gokhan Erkavun <gerkavun@gmail.com> wrote:
Hi Deniz,

I want to introduce you Satheesh our AI and Technical Executive of our company RightAgents Technologies Inc.

Satheesh reviewed the documents you shared with me and the following comments and information posted below.

To further discuss the scope and the details of the
project, I will create a Google Meet at 5 pm EST today. Please advise this time still good?

Looking forward to talk further.

Regards,
Gokhan

————————————————
Satheesh’s notes below:

Thanks for sending this over. I've gone through the deck and the tracker. 

The UN scores how well each country delivers government services online. It's a survey across 193 countries, run every two years, and today it all sits in Google Sheets. That setup has no history tracking, no clean way to manage the different people who touch the data (governments self-report, independent assessors check, UN staff approve), and no audit trail when a score is disputed. 

They want to move to a proper platform that stores every cycle, tracks progress over time, manages those user roles, and uses AI to catch problems and flag where each country should improve.

What we'd build breaks into four parts: form-based data intake to replace the spreadsheets, an AI layer that scans government sites and cross-checks answers for contradictions, an automatic scoring engine with versioning, and publication out to public pages and APIs. 

A few things I'd want Deniz to clarify Monday so we scope this tightly:

  - Are we doing just the design package and mock-up, or the build too?
  - Is the AI scope (website scanning, cross-source checks, anomaly flags) firm or aspirational?
  - Are survey responses all in English, or multiple languages? That changes the AI effort a lot.
  - How many past cycles of Google Sheets data exist to migrate?

