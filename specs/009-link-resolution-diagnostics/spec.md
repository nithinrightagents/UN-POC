# Feature Specification: Link Resolution Diagnostics

**Feature Directory**: `specs/009-link-resolution-diagnostics`
**Created**: 2026-08-21
**Status**: Draft
**Input**: The agent production pipeline is not able to correctly get these links. We make Claude Code get the links to check if they exist, and why the agent production pipeline is not able to solve it.

## Overview

The USA 50-question run answered "No" or "no suggestion" for 36 of 50 indicators. That number was read, at first, as a finding about the United States. It was not. Checking the questions by hand established that correct, admissible, national-government pages exist for most of them — `usa.gov/health`, `usa.gov/education` and `usa.gov/visas` were all sitting in the portal's own sitemap while the pipeline reported nothing there. The answers were artifacts of the machinery, and a survey that reports a country has no cybersecurity legislation because a search engine was asked the wrong question is worse than a survey that reports nothing at all.

Eight defects in link resolution were subsequently found and fixed. Every one of them was found the same way: by taking a question, working out by hand what the right link was, and then asking why the resolver had not produced it. That method worked, but it was performed with throwaway scripts calling the resolver directly. **The production pipeline was never run.** So the fixes are, strictly speaking, unvalidated where it counts, and the project cannot presently answer the only question that matters: when the pipeline says "No", is that because the link could not be found, or because the link was found and the assessor read the page and disagreed?

Those two failures look identical in the export and need completely different repairs. Conflating them is what allowed eight resolution defects to survive four consecutive runs.

This feature makes that distinction a permanent, repeatable property of the system rather than something a person rediscovers by hand. It records, per question, the link a competent human researcher established as correct — the **reference link** — then runs the real pipeline and reports, for every divergence, **which stage lost it and why**. The pipeline already records enough to answer that: every link source attempt carries its own rejection reason, the escalation flag says whether the search ever left the portal, the evidence gate says whether a found link was refused on locus grounds, and the assessor records its own rationale. Today that evidence is scattered across tables and read only when someone goes looking. This feature turns it into the output.

Critically, this extends the existing benchmark subsystem rather than standing beside it. Benchmark mode already drives the identical production pipeline through the same batch entry point, already isolates ground truth so it can never leak into the run, and already writes to its own session so production history is untouched. What it lacks is that its ground truth is only the *answer* — the yes or no. It has no concept of a correct *link*, and no concept of attributing a wrong answer to a stage. Those two gaps are this feature.

## Clarifications

### Session 2026-08-21

- Q: When the pipeline resolves a different URL than the reference, but that URL is a legitimate, admissible national-government page on the same topic, is that a pass, a fail, or something else? → A: A three-way verdict — match, divergent-plausible, or miss. Divergent-plausible is listed for human review and excluded from the headline pass rate.
- Q: FR-LD-021 compares the final answer against "the expected answer", but the spec never said where expected answers live. Where do they come from? → A: One version-controlled fixture carries both the reference link and the expected answer, loaded into the benchmark ground-truth store at run time.
- Q: Should a detected link-resolution regression fail an automated check and block a merge, or is this feature report-only? → A: Report-only by default, with an opt-in flag that exits non-zero on regression.
- Q: SC-004 said a resolution-only run must be "fast enough to sit inside an edit-measure-edit loop", which is not measurable. What bound should hold? → A: Under five minutes for the seeded set.

## Decisions Taken

- **D1 — The reference link is fixture data, established out of band, never derived at run time.** If the harness computed the right answer itself it would be testing one resolver against another resolver, and would agree with itself precisely where both are wrong. The reference is written down by a person, reviewed like code, and version-controlled.
- **D2 — The comparison extends benchmark mode rather than introducing a second harness.** Running the genuine pipeline, isolating ground truth from the run, and leaving production history untouched are all existing guarantees. Re-implementing them would create a harness free to drift from the pipeline it is supposed to measure — the exact failure this feature exists to prevent.
- **D3 — A missing reference question is an error, never a silent skip.** The cycle currently under test is missing two of the thirteen indicators that have established references. A filter that quietly matches eleven of thirteen reports a pass over a smaller set than the operator believes they ran, which is how a coverage gap becomes invisible.
- **D4 — "No correct link exists" is a first-class reference value.** Some indicators have no correct national deep link at all: United States driver's licences are issued by states, so every national candidate is wrong and the honest pipeline output is the portal's own page rather than any one state's DMV. A reference format that can only express "the right answer is this URL" would score the correct behaviour as a failure.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An engineer learns which stage lost a link (Priority: P1)

An engineer suspects link resolution is producing wrong answers. They run the diagnostic over a set of questions with established reference links and receive, per question, whether the pipeline reached the reference link and — when it did not — the named stage that lost it, together with that stage's own stated reason.

**Why this priority**: This is the feature. Everything else supports it. Without stage attribution a wrong answer is a mystery costing a day of manual bisection, which is what let eight defects survive four runs.

**Independent Test**: Take a question whose reference link is known and whose pipeline result is known to be wrong. Run the diagnostic and confirm the report names one stage and quotes that stage's recorded reason, rather than reporting only that the answer was wrong.

**Acceptance Scenarios**:

1. **Given** a question whose reference link the pipeline resolved exactly, **When** the diagnostic runs, **Then** the question is reported as a link match and the source that supplied it is named.
2. **Given** a question where no link source produced any candidate, **When** the diagnostic runs, **Then** the report names each source consulted, in order, with the reason each gave for producing nothing.
3. **Given** a question where a candidate was found but refused by the evidence-locus gate, **When** the diagnostic runs, **Then** the report identifies the gate as the losing stage, names the refused URL, and states the gate's reason.
4. **Given** a question where the search never left the portal because the portal produced a plausible but wrong page, **When** the diagnostic runs, **Then** the report distinguishes this from the case where the search did widen and still found nothing.
5. **Given** a question where the pipeline resolved the reference link exactly but the final answer was still negative, **When** the diagnostic runs, **Then** the report attributes the failure to assessment rather than resolution, and includes the assessor's recorded rationale.
6. **Given** a run over a set of questions, **When** it completes, **Then** the report summarises how many failures were resolution failures and how many were assessment failures, because the two have different owners and different fixes.

---

### User Story 2 - Reference links are curated, reviewable, and honest about their own limits (Priority: P1)

A researcher records the correct link for an indicator, including the case where no correct link exists, and marks how confident they are. A reviewer can see what was claimed and on what date, and can tell an authoritative reference from a provisional one.

**Why this priority**: The reference set is the measuring instrument. An unreviewable or overconfident reference set produces confident wrong verdicts about the pipeline, which is worse than no measurement because it would be trusted.

**Independent Test**: Add a reference for an indicator with no valid national link, and a reference marked provisional, and confirm both round-trip through a run and are reported distinctly from an ordinary confident reference.

**Acceptance Scenarios**:

1. **Given** an indicator with a known correct deep link, **When** a reference is recorded, **Then** it captures the URL, the date it was verified, and the origin of the claim.
2. **Given** an indicator for which no correct national link exists, **When** a reference is recorded, **Then** it expresses that explicitly, and the pipeline returning the portal's own page is scored as correct rather than as a miss.
3. **Given** a reference known to be weak — a thin or generic page standing in for a better one not yet located — **When** it is recorded, **Then** it is marked provisional and the report separates provisional results from authoritative ones in its totals.
4. **Given** a reference whose URL no longer serves a page, **When** the diagnostic runs, **Then** it reports the reference as stale and does not charge the failure to the pipeline.
5. **Given** a reference set and a question filter, **When** the filter names an indicator absent from the cycle under test, **Then** the run fails and names the missing indicator rather than proceeding over a smaller set.

---

### User Story 3 - Resolution can be measured without paying for assessment (Priority: P2)

An engineer iterating on ranking or admissibility runs the diagnostic in a mode that stops after links are resolved, getting link-level results quickly and without incurring model cost for pages it is not going to read.

**Why this priority**: Resolution defects were fixed in tight iterations — a ranking weight changed, then re-measured, many times over. A loop that also pays for assessment on every turn is slow enough that people stop using it and go back to ad-hoc scripts, which is the habit this feature replaces.

**Independent Test**: Run the same question set twice, once resolution-only and once end to end, and confirm the link-level verdicts agree and that the resolution-only run performs no assessment.

**Acceptance Scenarios**:

1. **Given** a resolution-only run, **When** it completes, **Then** every question carries a link verdict and no assessment is attempted.
2. **Given** a resolution-only run, **When** the report is produced, **Then** answer-level comparisons are marked as not evaluated rather than reported as failures.
3. **Given** an end-to-end run, **When** it completes, **Then** both link-level and answer-level verdicts are present for every question.

---

### User Story 4 - A regression in link quality is caught before it ships (Priority: P3)

Results from a run are retained so a later run can be compared against an earlier one, surfacing indicators that previously reached their reference link and no longer do.

**Why this priority**: The eight defects were introduced over time and noticed only after a full survey run produced implausible output. Comparing runs shortens that feedback loop, but it is worth less than being able to diagnose a single run at all, so it follows the first three stories.

**Independent Test**: Record a run, degrade a resolution input so a known-good indicator fails, run again, and confirm the comparison names that indicator as newly regressed rather than merely reporting a lower total.

**Acceptance Scenarios**:

1. **Given** two completed runs over the same reference set, **When** they are compared, **Then** indicators that changed verdict are listed individually with their before and after stage attribution.
2. **Given** two runs where the totals are identical but different indicators failed, **When** they are compared, **Then** the change is still surfaced rather than masked by the unchanged total.

---

### Edge Cases

- A reference link redirects to a different URL. The pipeline resolving the redirect target is a match, not a miss.
- The reference and the resolved URL differ only in scheme, `www`, trailing slash, or tracking parameters. These are the same page and must not be reported as a divergence.
- The pipeline resolves a page different from the reference but arguably just as valid — a cybersecurity-legislation question landing on one federal agency's page when the reference names another. See FR-LD-036.
- A government site is unreachable during the run. This is an environmental failure and must be reported as such, never as a resolution defect.
- The reference set and the cycle disagree about which indicators exist, in either direction.
- A run is interrupted part way. Partial results must be identifiable as partial.
- Two indicators legitimately share one reference link — the health-services question and the health-expenditure question may both point at the same page.

## Functional Requirements *(mandatory)*

#### The reference set

- **FR-LD-001**: The system MUST store a reference link per indicator per country, held as version-controlled fixture data separate from the assessment database.
- **FR-LD-002**: A reference entry MUST record the expected URL, the date it was last verified, and the origin of the claim.
- **FR-LD-003**: A reference entry MUST be able to express that no correct link exists for that indicator, distinctly from an absent or unknown reference.
- **FR-LD-004**: A reference entry MUST carry a confidence marker distinguishing authoritative from provisional references.
- **FR-LD-005**: A reference entry MAY list additional URLs accepted as equally correct.
- **FR-LD-006**: The reference set MUST be seeded with the thirteen indicators whose links have already been established: #030, #043, #045, #054, #055, #092, #095, #108, #336, #337, #339, #340, #341.
- **FR-LD-007**: References for #054 and #339 MUST be recorded as provisional with the reason stated: #054 has no valid national link because the service is issued subnationally, and #339's known target is a thin generic page rather than the right-to-information page the indicator asks for.
- **FR-LD-008**: Reference ground truth MUST NOT be readable by any component of the assessment pipeline during a run.
- **FR-LD-034**: A reference entry MUST record the expected answer for its indicator alongside the expected URL, in the same fixture, so link truth and answer truth cannot drift apart. The expected answer MUST be stated explicitly rather than inferred from whether a reference URL is present, since an indicator may correctly answer "No" even though a page on the topic exists.
- **FR-LD-035**: Expected answers MUST be loaded from the fixture into the isolated ground-truth store used by benchmark runs, rather than maintained separately in the database, so that the fixture remains the single reviewable source of truth.

#### Running the diagnostic

- **FR-LD-009**: The diagnostic MUST execute the production assessment pipeline through the same entry point production runs use, rather than any reimplementation of it.
- **FR-LD-010**: The diagnostic MUST support restricting a run to a named set of indicators.
- **FR-LD-011**: The diagnostic MUST fail, naming the specific indicators, when the requested set includes any indicator absent from the cycle under test or absent from the reference set.
- **FR-LD-012**: The diagnostic MUST support a resolution-only mode that stops before assessment.
- **FR-LD-013**: A diagnostic run MUST NOT alter, overwrite, or delete any production run history, answer, or export.
- **FR-LD-014**: A diagnostic run MUST record the configuration it ran under, so a result can be tied to the settings that produced it.
- **FR-LD-015**: An interrupted run MUST be identifiable as incomplete and MUST NOT be reported as though it covered the full set.

#### Comparison

- **FR-LD-016**: The system MUST compare each resolved link against its reference, treating differences of scheme, `www` prefix, trailing slash, and tracking parameters as equivalent.
- **FR-LD-017**: The system MUST treat a resolved link that redirects to the reference, or is redirected to from it, as a match.
- **FR-LD-018**: The system MUST treat any URL listed as an accepted alternative as a match.
- **FR-LD-019**: When a reference expresses that no correct link exists, the system MUST score the pipeline's documented correct behaviour for that case as a pass.
- **FR-LD-020**: The system MUST verify that each reference URL still serves a page, and report one that does not as stale rather than charging the divergence to the pipeline.
- **FR-LD-021**: In end-to-end mode the system MUST additionally compare the pipeline's final answer against the expected answer recorded for that indicator under FR-LD-034.
- **FR-LD-036**: Each link comparison MUST yield one of exactly three verdicts: **match** (the reference, an accepted alternative, or an equivalent form of either), **divergent-plausible** (a different URL that is nonetheless an admissible national-government page on the indicator's topic), or **miss** (anything else, including no link at all).
- **FR-LD-037**: Divergent-plausible results MUST be excluded from the headline pass rate and listed individually for human review, so that a genuine equivalent can be promoted into that reference's accepted alternatives under FR-LD-005 and a wrongly-flattering result is never silently counted as a pass.

#### Stage attribution

- **FR-LD-022**: For every divergence the system MUST identify the responsible pipeline stage, drawn from a closed set covering at minimum: each ordered link source, the evidence-locus gate, the off-portal escalation, page retrieval, and assessment.
- **FR-LD-023**: The system MUST report, for each link source consulted, whether it was reached, what it returned, and the reason it recorded for returning nothing usable.
- **FR-LD-024**: The system MUST report whether the search widened beyond the portal, and distinguish "never widened because the portal produced a candidate" from "widened and still found nothing".
- **FR-LD-025**: When a candidate was refused by the evidence-locus gate, the system MUST name the refused URL and report the gate's stated reason.
- **FR-LD-026**: When the reference link was resolved correctly but the final answer was still negative, the system MUST attribute the failure to assessment and include the assessor's recorded rationale.
- **FR-LD-027**: The system MUST report when the evidence page was retrieved but truncated before being given to the assessor, since evidence beyond the truncation point cannot influence the answer and is otherwise indistinguishable from absent evidence in the assessor's output.
- **FR-LD-028**: The system MUST distinguish environmental failures — unreachable hosts, timeouts, exhausted API quota — from pipeline defects, and MUST NOT count them as resolution failures.

#### Reporting

- **FR-LD-029**: The system MUST produce a per-indicator report giving the reference, the resolved link, the verdict, and the attributed stage with its reason.
- **FR-LD-030**: The report MUST summarise totals separating resolution failures from assessment failures.
- **FR-LD-031**: The report MUST present provisional-reference results separately from authoritative ones, so a headline figure is never inflated by references not yet trusted.
- **FR-LD-032**: Run results MUST be retained so that two runs over the same reference set can be compared.
- **FR-LD-033**: A comparison of two runs MUST list indicators whose verdict changed, in both directions, individually.
- **FR-LD-038**: A run MUST be report-only by default, signalling success regardless of how many indicators failed, and MUST offer an explicit opt-in under which a regression signals failure to a caller. Report-only is the default because a run depends on live government sites and a paid search API, so a third-party outage must not be indistinguishable from a code defect.

### Key Entities

- **Reference Link** — the correct evidence URL for one indicator and country, as established by a human researcher, together with that indicator's expected answer. Carries verification date, origin, confidence, optional accepted alternatives, and the explicit "no correct link exists" case. Version-controlled; invisible to the pipeline during a run.
- **Diagnostic Run** — one execution of the production pipeline over a chosen indicator set against a chosen reference set, in resolution-only or end-to-end mode. Carries the configuration it ran under and whether it completed.
- **Indicator Verdict** — the outcome for one indicator in one run: the link verdict (match, divergent-plausible, or miss), whether the answer matched, and where either diverged, the attributed stage and its recorded reason.
- **Stage Attribution** — the named pipeline stage held responsible for a divergence, drawn from a closed set, together with that stage's own recorded explanation.
- **Run Comparison** — the difference between two runs over the same reference set, expressed as indicators that changed verdict rather than as a change in totals.

## Success Criteria *(mandatory)*

- **SC-001**: For every indicator that fails, a reader of the report can name the responsible stage without opening the database or reading any code.
- **SC-002**: An engineer can tell, for any negative answer, whether the cause was a link that was never found or a page that was found and read differently — a distinction currently impossible from the export.
- **SC-003**: The thirteen seeded indicators can be re-measured on demand by one command, with no manual preparation between runs.
- **SC-004**: A resolution-only measurement over the seeded thirteen indicators completes in under five minutes and incurs no assessment cost.
- **SC-005**: A regression that breaks link resolution for a previously passing indicator is identified by name when two runs are compared.
- **SC-006**: A run over a reference set naming an indicator the cycle does not contain fails loudly, and never reports a result covering fewer indicators than requested.
- **SC-007**: No diagnostic run changes any production answer, run record, or export.
- **SC-008**: A stale reference — one whose own URL has died — is reported as a reference problem and never as a pipeline defect.

## Assumptions

- Reference links are established by a human researcher using ordinary web research, not by any automated resolver. Where this document says a link was "established", it means a person checked the page and confirmed it answers the indicator.
- The existing benchmark subsystem's guarantees are relied upon rather than re-specified: it drives the genuine production pipeline, isolates ground truth from the run, and writes to a session separate from production cycles.
- Expected answers are recorded explicitly per indicator rather than inferred from the presence of a reference link. For the seeded thirteen they are expected to be "Yes" in most cases, but the fixture states each one so that an indicator whose correct answer is "No" can be expressed.
- Live network access to government sites and to the configured search provider is available during a run. Their absence is an environmental failure under FR-LD-028, not a defect.
- Runs cost money in model and search-API usage, and are therefore operator-triggered rather than automatic.
- The seeded set is a starting point sized for iteration, not a claim of statistical coverage over the questionnaire.

## Dependencies

- The existing benchmark subsystem, including benchmark-mode sessions, isolated ground-truth storage, and its measures.
- The production scheduler and its command-line entry point, which the diagnostic must invoke rather than reimplement.
- The link resolution chain's recorded per-source attempt history and rejection reasons, which are the raw material for stage attribution — attribution is only as good as what each source records about why it declined.
- The evidence-locus gate's recorded verdict and reason.
- The assessor's recorded rationale.
- The `usa-test-2026` cycle, which currently lacks indicators #108 and #092 and must be completed before the full seeded set can be measured.

## Out of Scope

- Fixing any defect this feature reveals. This measures; it does not repair.
- Establishing reference links for indicators beyond the seeded thirteen.
- Extending reference sets to countries other than the United States.
- Changing how the pipeline resolves links, ranks candidates, or assesses pages.
- Replacing the search provider.
- Any change to what human assessors see or do.
