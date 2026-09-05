# Feature Specification: Unit-Level Assessor Assignment

**Feature Directory**: `specs/014-unit-assessor-auto-assignment`
**Created**: 2026-09-05
**Status**: Draft
**Input**: "the assesor assignment is not at a project level but at a country / city level i.e unit level. Have a dummy db containing assesor information and make the program auto assign the assesors from the DB." — refined: "instead of having assesor at project level it is at unit level. Nothing else. Project can be of national or city type, not both." — and: "the assesors are stored in a DB for the relevant units and is just ingested in the portal. The assesors are always pre-ingested; the admin changes if needed."

---

## Overview

Today a survey project has exactly one pair of human assessors. Whoever is named Assessor A on the project is the A-role assessor for every unit in it, and an administrator types both email addresses by hand into a single form before the project locks.

This feature moves that pairing down one level. **Assessor A and Assessor B become properties of a unit, not of the project.** Each country in a national project, or each city in a city project, carries its own assessor pair, so different units in the same project are worked by different people.

Who those people are is not a decision the portal makes. **An assessor database already records which assessors cover which units**, and the portal ingests that mapping ahead of use. When a project contains a unit the mapping covers, that unit arrives already staffed with its Assessor A and Assessor B. The administrator changes any of it afterwards if the situation calls for it.

The real assessor database will be supplied by the programme. Until it arrives, the platform carries seeded demonstration data of the same shape — assessor records and their unit mapping — so the workflow runs end to end without anyone entering assessor details by hand.

The blind-assessment guarantee is unchanged and load-bearing: A and B on a unit must be two different people, and neither sees the other's submissions before reconciliation. Moving assignment to the unit turns that from something an administrator has to get right by hand into a rule the platform enforces on every assignment, ingested or manual.

### Scope boundary

This changes *where assignment lives* and *where the pair comes from*. It does not change the questionnaire, the submission workflow, the completion declaration, the discrepancy calculation, reconciliation, or publication — all of which already operate per unit and continue untouched.

The portal performs **no assessor selection of any kind**. It does not match assessors to units by language, region, capacity, or workload, and it does not balance load across a panel. The source database decides who assesses what; the portal applies that decision and lets an administrator correct it.

---

## Decisions Taken

- **D1 — The unit is the assignment boundary.** Assessor A and Assessor B are properties of a unit within a project. The project-level assessor pair is retired as the source of truth.
- **D2 — A project is national or city, never both.** A project's type fixes the classification of every unit in it: a national project's units are all countries, a city project's units are all cities. Assignment behaves identically for both, and no project holds a mixture.
- **D3 — The source database names the pair; the portal applies it.** The database holds an explicit mapping from a unit to its Assessor A and Assessor B. The portal ingests that mapping and uses it verbatim. No selection, matching, ranking, or load-balancing logic exists in the portal.
- **D4 — The mapping is keyed by unit identity, not by project.** A mapping entry identifies its unit by country or city code plus national/city classification, so the source database needs no knowledge of the portal's projects. Any project containing that unit starts from the same pair; per-project deviation is what override is for.
- **D5 — Ingestion happens ahead of use, not as a running sync.** Assessor records and their mapping are pre-ingested as a setup-time load. There is no continuous background synchronisation, so no later ingest arrives to contest an administrator's decision.
- **D6 — Units are staffed automatically from the pre-ingested mapping.** A unit that the mapping covers is assigned its pair without any administrator action, at the point the unit comes into existence in a project.
- **D7 — Administrator override is always available, from the portal.** Either role on any unit can be changed to any assessor on record, at any time, from the project's own administration screens. Override is bound by the distinctness rule and never overwritten by the platform.
- **D8 — What the mapping cannot supply is left visibly unstaffed.** A unit the mapping does not cover, or covers invalidly, is left unstaffed with a stated reason rather than half-assigned or silently skipped. The platform never invents an assessor and never pairs a person with themselves.
- **D9 — Reassignment preserves submitted work.** Answers already submitted for a role on a unit stay attached to that unit and role and remain visible to whoever holds the role next. Reassignment records who replaced whom and when. Submissions are never deleted or reattributed.
- **D10 — Assignment gates the assessor workspace.** An assessor opens a unit because they are assigned to it, and their role follows from that assignment rather than from a value supplied in the request.
- **D11 — Staffing status is per unit.** A project is described by how many of its units are staffed rather than by a single locked/unlocked flag. A unit becomes workable once both its roles are filled, so one country can be under assessment while another still awaits an assessor.

---

## Clarifications

### Session 2026-09-05

- Q: What is a "unit"? → A: One country portal or one city portal within one project — the granularity the platform already uses for portal URL, MSQ upload, submissions, completion, discrepancy, and publication.
- Q: Can a project contain both country units and city units? → A: No. A project is either national or city type, and every unit in it takes that classification. Assignment is identical for both types; no project mixes them.
- Q: Does the assessor database name the assessors per unit, or list assessors eligible for units? → A: It names them. The database holds an explicit mapping of unit → Assessor A and Assessor B, which the portal ingests and applies verbatim. No selection logic exists in the portal; language, region, capacity, and workload play no part in who is assigned.
- Q: When is the database ingested, and what happens to administrator overrides if it is ingested again? → A: Assessors are pre-ingested ahead of use, as a setup-time load rather than a recurring sync. The administrator changes assignments afterwards, so no ongoing ingestion exists to overwrite an override.
- Q: What does a mapping entry key on — the unit globally, or the unit within a project? → A: Unit identity: country or city code plus national/city classification, independent of any project. The source database needs no knowledge of the portal's internal project identifiers.
- Q: What identifies an assessor on a submission? → A: The stable identifier carried on the ingested assessor record.
- Q: Is the assessor database a real integration yet? → A: Not yet. The programme will supply it; for now the platform carries seeded demonstration data of the same shape, so the workflow is exercisable end to end and the real source can replace the seed without reworking assignment.
- Q: Can the same person be A on one unit and B on another? → A: Yes. Distinctness is a per-unit rule. Forbidding it more widely would constrain the source database for no benefit to blindness.
- Q: What happens to existing submissions when a unit's assessor is replaced? → A: Preserved intact, attached to the unit and role, visible to the incoming assessor, with the change of custody recorded.
- Q: Does this feature manage assessor records themselves — adding, editing, deactivating assessors? → A: No. They are ingested, not administered here. That belongs with the real assessor database.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A project's units arrive already staffed (Priority: P1)

An administrator creates a national project and adds twelve country units to it. They name no assessors. Each unit appears with its own Assessor A and Assessor B, taken from the pre-ingested mapping — two different people per unit, differing from unit to unit. The twelve units are immediately workable.

**Why this priority**: This is the feature. It replaces one project-wide pair typed by hand with per-unit pairs the source database already knows.

**Independent Test**: With the mapping pre-ingested, create a project with several units and verify each unit holds its own distinct pair without any administrator input.

**Acceptance Scenarios**:

1. **Given** a pre-ingested mapping covering a project's units, **When** the administrator adds those units to the project, **Then** each unit is assigned the Assessor A and Assessor B the mapping names for it, without any administrator action.
2. **Given** a staffed project, **When** the administrator views any unit, **Then** it shows its own assessor pair, which may differ from every other unit in the project.
3. **Given** a staffed project, **When** the administrator views the project, **Then** it reports how many units are staffed and how many are not.
4. **Given** a unit added to a project after the others, **When** the mapping covers that unit, **Then** it is staffed on creation like the rest.
5. **Given** two projects each containing the same unit identity, **When** both are viewed, **Then** each starts from the pair the mapping names for that unit.

---

### User Story 2 - Different units in the same project are worked by different assessors (Priority: P1)

A project covers Kenya and Brazil, staffed from the mapping with two different pairs. Kenya's A-role assessor opens Kenya's questionnaire and works it. When that same person tries to open Brazil's questionnaire, they are refused — they are not assigned to it. Within Kenya, A and B still cannot see each other's answers.

**Why this priority**: This is the observable consequence of unit-level assignment, and where its access-control implications are proven.

**Independent Test**: Staff two units with disjoint pairs, then verify each assessor reaches only their own unit, in the correct role, with blindness intact.

**Acceptance Scenarios**:

1. **Given** an assessor assigned as A on a unit, **When** they open it, **Then** they see it in the A role with only their own prior submissions.
2. **Given** an assessor not assigned to a unit in either role, **When** they attempt to open it, **Then** access is refused and no questionnaire content, submission, or evidence is disclosed.
3. **Given** an assessor assigned as B on a unit, **When** they open it, **Then** they are placed in the B role regardless of any role supplied in the request, and see none of the A-role submissions.
4. **Given** an assessor assigned as A on one unit and B on another, **When** they open each, **Then** each opens in its own correct role.
5. **Given** a unit with only one role filled, **When** assessment is attempted on it, **Then** the unit is treated as unstaffed and not workable.

---

### User Story 3 - An administrator changes an assigned assessor (Priority: P1)

Reviewing a project staffed from the mapping, an administrator judges one unit's Assessor B unsuitable — that person lacks the local context the unit needs. From the project's unit list they pick a different assessor on record for that role. The change takes effect immediately, affects only that unit, and the replaced assessor loses access to it. Later, mid-cycle, an assessor leaves the panel and the administrator replaces them on the three units they held; the answers each had already submitted remain in place for their replacements to continue from.

**Why this priority**: Assignment arriving from an external database is only acceptable because it is correctable. Without override a wrong pairing would be unfixable, and mid-cycle staffing changes are ordinary in a real survey.

**Independent Test**: Change one unit's assessor from the portal and verify only that unit changed. Then submit answers, reassign that role, and verify the answers survive and the incoming assessor sees them.

**Acceptance Scenarios**:

1. **Given** a staffed unit, **When** the administrator assigns a different assessor to one of its roles, **Then** that unit's assignment changes and no other unit is affected.
2. **Given** two projects containing the same unit identity, **When** the administrator overrides one project's unit, **Then** the other project's unit is unchanged.
3. **Given** an override in progress, **When** the administrator chooses a replacement, **Then** they can see each candidate's name, contact, and descriptive details on record.
4. **Given** an override naming the same person for both roles of a unit, **When** it is submitted, **Then** it is refused with a clear explanation.
5. **Given** a unit with submitted answers for a role, **When** that role is reassigned, **Then** every existing submission is preserved and none is deleted or reattributed.
6. **Given** a reassigned role, **When** the incoming assessor opens the unit, **Then** they see the role's prior submissions and can continue from them.
7. **Given** a reassignment, **When** the outgoing assessor attempts to open the unit, **Then** access is refused.
8. **Given** a reassignment with no new submission, **When** the unit is inspected, **Then** its completion status and discrepancy state are unchanged.

---

### User Story 4 - Gaps in the source data are visible, not silent (Priority: P2)

An administrator adds eight units to a project, but the mapping covers only five of them, and a sixth names the same person for both roles. Those three units appear unstaffed, each with a stated reason. The administrator assigns them by hand, and the five already staffed are undisturbed.

**Why this priority**: Silent under-staffing is worse than manual assignment, because a unit would look ready when nobody is responsible for it.

**Independent Test**: Ingest a mapping with deliberate gaps and conflicts, add the units, and verify partial staffing with per-unit reasons and no half-assigned or duplicated pairing.

**Acceptance Scenarios**:

1. **Given** units the mapping does not cover, **When** they are added to a project, **Then** each is reported unstaffed with that reason.
2. **Given** a mapping entry naming the same person for both roles of a unit, **When** it is applied, **Then** the unit is left unstaffed and the conflict reported, rather than staffed with one person twice.
3. **Given** a mapping entry naming only one of the two roles, **When** it is applied, **Then** the unit is reported unstaffed and not workable.
4. **Given** a mapping entry referencing an assessor not on record, **When** it is applied, **Then** the unit is left unstaffed and the unknown reference reported.
5. **Given** unstaffed units, **When** the administrator assigns them by hand, **Then** they become staffed without disturbing units already assigned.

---

## Edge Cases

- **A mapping entry for a unit no project contains.** Ignored without error; it becomes relevant only if a project later contains that unit.
- **A mapping entry naming one person for both roles.** Refused for that unit. Distinctness is never negotiable, for ingested and manual assignments alike.
- **A mapping entry referencing an unknown assessor.** Refused for that unit and reported; the unit stays unstaffed rather than half-assigned.
- **A unit added to a project long after ingestion.** Staffed from the pre-ingested mapping on creation, exactly as the original units were.
- **A unit whose assignment an administrator has already set.** Never overwritten by the platform applying the mapping.
- **The same unit identity in two different projects.** Both start from the same mapped pair; an override in one project does not touch the other.
- **A project migrated from the retired project-level model.** The project's existing pair is carried down to every unit, so no in-flight work is orphaned and no submission loses its role attribution.
- **A unit reaching reconciliation after a reassignment.** Reconciliation compares the unit's A-role and B-role answers of record, regardless of which individuals submitted them.
- **Two administrators changing the same unit concurrently.** Assignment state stays consistent; a unit never ends up with a duplicated or half-applied pairing.

---

## Functional Requirements *(mandatory)*

### Assessor Source Data

- **FR-DB-001**: The platform MUST hold persisted assessor records, each with a stable identifier, a display name, a unique contact email, and descriptive details shown to an administrator for context.
- **FR-DB-002**: The platform MUST hold a persisted unit-assessor mapping, each entry identifying a unit by country or city code plus its national/city classification and naming that unit's Assessor A and Assessor B.
- **FR-DB-003**: Both MUST be pre-populated at initialisation with demonstration data covering enough units to staff a multi-unit project without any manual data entry.
- **FR-DB-004**: Population MUST be idempotent, so re-initialising does not duplicate records or mapping entries.
- **FR-DB-005**: The shape of both MUST allow the demonstration data to be replaced by the externally supplied assessor database without changing how assignment consumes it.
- **FR-DB-006**: Descriptive details on an assessor record MUST NOT influence which assessor is assigned to any unit; the mapping alone determines that.
- **FR-DB-007**: An administrator MUST be able to view the assessor records on file.

### Ingestion and Application

- **FR-IN-001**: Assessor records and their mapping MUST be ingested ahead of use as a setup-time load, not maintained by a recurring background synchronisation.
- **FR-IN-002**: When a unit exists in a project and the mapping covers that unit's identity, the platform MUST assign the mapped Assessor A and Assessor B to it without any administrator action.
- **FR-IN-003**: The mapping MUST be applied at the point a unit comes into existence in a project, so units added later are staffed on creation.
- **FR-IN-004**: The platform MUST apply the mapping verbatim and MUST NOT select, rank, match, or substitute assessors on any basis of its own.
- **FR-IN-005**: A mapping entry naming the same assessor for both roles of a unit MUST be refused for that unit, leaving it unstaffed with the conflict reported.
- **FR-IN-006**: A mapping entry referencing an assessor not on record MUST be refused for that unit, leaving it unstaffed with the unknown reference reported.
- **FR-IN-007**: A mapping entry naming only one of the two roles MUST leave the unit unstaffed and reported.
- **FR-IN-008**: A unit whose identity the mapping does not cover MUST be reported unstaffed with that reason.
- **FR-IN-009**: A mapping entry whose unit identity matches no unit in any project MUST be ignored without error.
- **FR-IN-010**: Applying the mapping MUST NOT overwrite an assignment an administrator has set.
- **FR-IN-011**: The platform MUST report, per project, which units the mapping staffed and which it left unstaffed with the reason for each.

### Unit-Level Assignment

- **FR-UA-001**: Every unit MUST be capable of carrying its own Assessor A and Assessor B, independently of every other unit.
- **FR-UA-002**: A unit's Assessor A and Assessor B MUST always be two distinct assessors; any assignment naming the same assessor for both roles on one unit MUST be refused, whether ingested or manual.
- **FR-UA-003**: Different units within the same project MUST be able to hold entirely different assessor pairs.
- **FR-UA-004**: The same assessor MUST be able to hold different roles on different units, including within one project.
- **FR-UA-005**: A unit MUST be workable only when both of its roles are filled; a unit with one or neither role filled MUST be reported unstaffed.
- **FR-UA-006**: The project-level assessor pair MUST be retired as the source of assignment truth, and the platform MUST determine who works a unit solely from that unit's assignment.
- **FR-UA-007**: The platform MUST NOT fall back to any project-wide assessor when a unit is unstaffed.
- **FR-UA-008**: Projects staffed under the retired project-level model MUST be migrated by propagating the project's pair to every unit, preserving the role attribution of all existing submissions.
- **FR-UA-009**: A project MUST be of a single type — national or city — and every unit within it MUST take that project's classification; the platform MUST NOT permit a project to hold a mixture of country units and city units.
- **FR-UA-010**: Assignment, application of the mapping, override, and access control MUST behave identically for country units and city units.
- **FR-UA-011**: An assignment on one project's unit MUST be independent of any other project's unit sharing the same unit identity.

### Administrator Override

- **FR-MO-001**: An administrator MUST be able to assign either role on any individual unit to any assessor on record, whether that unit is unstaffed or already staffed.
- **FR-MO-002**: Override MUST be performed from the portal's project administration screens, alongside the unit it affects, without a separate tool or a direct data edit.
- **FR-MO-003**: When overriding, the administrator MUST see each candidate's name, contact, and descriptive details on record.
- **FR-MO-004**: An override naming the same assessor for both roles of a unit MUST be refused with a clear explanation.
- **FR-MO-005**: An administrator MUST be able to clear a role's assignment, returning the unit to unstaffed.
- **FR-MO-006**: Changing a role MUST preserve every existing submission for that unit and role; no submission may be deleted, reattributed, or rewritten.
- **FR-MO-007**: The incoming assessor for a changed role MUST see that role's existing submissions and be able to continue from them.
- **FR-MO-008**: Every assignment, change, and clearing MUST be recorded with the unit, role, outgoing and incoming assessor, acting administrator, and time.
- **FR-MO-009**: Changing a role without any new submission MUST leave the unit's completion status and discrepancy state unchanged.

### Access Control

- **FR-AC-001**: An assessor MUST be able to open a unit's questionnaire only if they are that unit's assigned Assessor A or assigned Assessor B.
- **FR-AC-002**: An assessor's role on a unit MUST be derived from that unit's assignment, never from a role value supplied in the request.
- **FR-AC-003**: An attempt to open a unit by anyone not assigned to it MUST be refused with a clear explanation, disclosing no questionnaire content, submission, or evidence.
- **FR-AC-004**: The existing blind-assessment guarantee MUST be preserved: neither role may read the other's submissions on a unit before reconciliation opens.
- **FR-AC-005**: Completion declaration on a unit MUST be permitted only to that unit's currently assigned assessor for the declared role.

### Staffing Visibility

- **FR-SV-001**: A project view MUST show, for every unit, its assigned Assessor A and Assessor B, or that the unit is unstaffed with the reason.
- **FR-SV-002**: A project view MUST state how many of its units are staffed and how many are not.
- **FR-SV-003**: Staffing views MUST reflect assignment changes immediately after they are made.

---

## Key Entities

- **Assessor** — a person on record, ingested from the source database. Stable identifier, display name, unique contact email, and descriptive details for administrator context. Independent of any project. Seeded now, externally supplied later.
- **Unit Assessor Mapping Entry** — the source database's statement of who assesses a unit: a unit identity (country or city code plus national/city classification) with its Assessor A and Assessor B. Carries no project reference.
- **Unit Assessor Assignment** — binds one assessor to one role (A or B) on one unit of one project. Carries the unit, project, role, assessor, how it was set (from the mapping, or by an administrator), and when. A unit is workable when both roles have a current assignment.
- **Assignment Change Record** — append-only record of an assignment being created, replaced, or cleared, naming the unit, role, outgoing and incoming assessor, acting administrator, and time.
- **Unit** *(existing, extended)* — a country or city portal within a project. Gains its own assessor pair and staffing status; retains its portal URL, MSQ document, language, submissions, completion, discrepancy state, and publication record.
- **Survey Project** *(existing, reduced)* — loses its project-level assessor pair and its wholesale locked/unlocked flag, gaining a derived staffed/unstaffed unit count. Retains its single national-or-city type, which fixes the classification of all its units.

---

## Success Criteria *(mandatory, measurable, technology-agnostic)*

- **SC-001**: A twelve-unit project covered by the mapping is fully staffed on creation, with the administrator entering no assessor details at all.
- **SC-002**: Across every assignment, ingested or manual, 100% of staffed units have two distinct assessors — no unit is ever staffed by one person in both roles.
- **SC-003**: 100% of units the mapping cannot staff are reported unstaffed with a specific reason, and zero units are left silently without a responsible assessor.
- **SC-004**: 100% of assignments applied to a unit match what the mapping names for it, with zero substitutions made by the platform.
- **SC-005**: An administrator can change either assessor on any unit entirely within the portal, in under thirty seconds, and only the targeted unit is affected.
- **SC-006**: No assignment set by an administrator is ever overwritten by the platform.
- **SC-007**: 100% of attempts by an unassigned person to open a unit's questionnaire are refused, with nothing disclosed.
- **SC-008**: Across any reassignment, 100% of previously submitted answers for the affected unit and role remain retrievable and visible to the incoming assessor.
- **SC-009**: Every assignment change is recoverable from the record, showing who held each unit role over which period.
- **SC-010**: A newly initialised platform can staff and complete a multi-unit project using only the pre-ingested demonstration data, with no manual assessor entry.
- **SC-011**: Every project staffed under the retired project-level model is migrated with zero submissions orphaned and zero role attributions lost.
- **SC-012**: Zero units are assessable while unstaffed — assessment cannot begin on a unit until both roles are filled.
- **SC-013**: Replacing the demonstration data with real assessor data changes which people are assigned, and nothing else about how units are staffed.

---

## Assumptions

- **A1**: An assessor's identity on a submission is the stable identifier carried on their ingested record.
- **A2**: A unit's identity for mapping purposes is its country or city code plus its national/city classification; country codes come from the platform's existing country reference data.
- **A3**: Assessor identity remains the demonstration-grade identity the portal already uses. This feature governs who is *assigned* to a unit and gates access on it, but introduces no password authentication or external identity provider.
- **A4**: The seeded assessor records and mapping are demonstration data — realistic in shape and sufficient to exercise every path, including the gap and conflict cases — but not real personnel records.
- **A5**: The Senior Reviewer role remains project-scoped and is unaffected; only Assessor A and Assessor B move to the unit.
- **A6**: Reconciliation continues to compare the A-role and B-role answers of record on a unit, independent of which individuals submitted them.
- **A7**: The source database is responsible for the suitability of the pairs it names — their language fit, regional knowledge, availability, and workload. The portal does not evaluate or second-guess them.

---

## Dependencies

- **D-1**: The existing unit model — a country or city portal within a project, already the granularity for portal URL, MSQ upload, submissions, completion, discrepancy, and publication.
- **D-2**: The existing role-scoped blind submission model, whose A/B separation this feature preserves and enforces by assignment.
- **D-3**: The existing country reference data, supplying the country codes that mapping entries key on.
- **D-4**: The existing administrative project surface, which gains the per-unit assignment display and override controls.
- **D-5**: The existing seeded-reference-data pattern, which the demonstration assessor data and mapping follow.
- **D-6**: The assessor database the programme will supply, which replaces the demonstration data without changing assignment behaviour.

---

## Known Limitations

- **L-1**: The portal cannot staff a unit the source database does not cover. Such units need an administrator to assign them by hand.
- **L-2**: The mapping is keyed by unit identity, so every project containing a given unit starts from the same pair. Per-project variation is achieved only by override.
- **L-3**: Ingestion is a setup-time load, so a change in the source database does not reach the portal until it is ingested again.
- **L-4**: The demonstration data has no connection to any external system until the real assessor database arrives.
- **L-5**: The portal cannot detect an unsuitable pairing, because it holds no criteria against which suitability could be judged. Correcting one depends on an administrator noticing it.

---

## Out of Scope

Deliberately excluded to hold this feature to moving assignment from the project to the unit:

- **Any assessor selection logic** — matching on language, region, or expertise; capacity limits; workload balancing; ranking or scoring candidates. The source database decides who assesses what.
- **Continuous synchronisation with the source database.** Ingestion is a setup-time load.
- **Assessor lifecycle management** — adding, editing, deactivating, or removing assessor records. They are ingested; their administration belongs with the real assessor database.
- **An approval gate on ingested assignments.** They apply directly; the administrator corrects afterwards.
- Authentication, credentials, or an external identity provider for assessors.
- Notifying assessors of their assignments through any channel.
- Assessor performance history or accuracy scoring.
- Calendar-aware scheduling, leave planning, or deadline-driven assignment.
- Self-service onboarding, or assessors choosing their own units.
- Any change to the Senior Reviewer role, reconciliation, discrepancy calculation, or publication.
- Any change to the questionnaire, indicator model, scoring, or evidence requirements.
- Reintroducing AI-driven prefill or AI-driven assignment recommendation.
