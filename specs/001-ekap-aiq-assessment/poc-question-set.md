# PoC Question Set: Module 2.1 — Institutional Framework

**Feature**: `specs/001-ekap-aiq-assessment` | **Source**: `Module 2.1 Institutional Framework.pdf` (UN DESA, Public Institutions) | **Recorded**: 2026-08-13

The proof of concept assesses **only** this question set. Referenced by [spec.md](./spec.md) §Assumptions.

**16 question rows covering 26 underlying indicator IDs.** Rows 12 and 13 each span six sectors — see [Multi-sector rows](#multi-sector-rows) below, which is the one structural wrinkle in this set.

## Questions

| # | Indicator ID(s) | Question | Description |
|---|---|---|---|
| 1 | #010 | Organizational structure | Information available on the organizational structure and/or chart of the government |
| 2 | #011 | Names/titles of heads of government agencies/departments/ministries | Information on government heads and contacts of head of department available on the national portal(s) |
| 3 | #012 | Links to sub-national/local government institutions/agencies | Existence of links to any local/regional/national government agencies |
| 4 | #014 | Privacy statement(s) | Existence of a privacy policy or statement available on the national portal |
| 5 | #342 | National e-Government/Digital Government strategy | Existence of a National e-Government/Digital Government strategy or equivalent |
| 6 | #339 | Citizens' rights to access government information | Information (content or documents) regarding users' rights to access government information |
| 7 | #338 | Legislation/law/policy/regulation on personal data protection | Existence of legislation/law/policy/regulation on personal data protection |
| 8 | #340 | Legislation/law/policy/regulation on cybersecurity | Existence of legislation/law/policy/regulation on cybersecurity |
| 9 | #337 | National CIO | Information/contact about a National CIO or equivalent |
| 10 | #345 | Legislation/law/policy/regulation on e-participation | Existence of legislation/law/policy/regulation on e-participation |
| 11 | #341 | Legislation/law/policy/regulation on Open Government Data | Existence of legislation/law/policy/regulation on Open Government Data |
| 12 | #090, #103, #119, #132, #161, #172 | Link to the sectoral or ministerial websites | Link to the sectoral or ministerial websites on Health / Education / Employment and/or Labor / Social Protection / Environment / Justice |
| 13 | #091, #104, #120, #133, #162, #173 | Information on policies related to different sectors | Information on policies related to Health / Education / Employment and/or Labor / Social Protection / Environment / Justice |
| 14 | #336 | Legislation/law/regulation against misinformation, disinformation and/or fake news | Existence of legislation/law/regulation against misinformation, disinformation and/or fake news |
| 15 | #343 | A cloud strategy or equivalent | Information on a cloud strategy or equivalent |
| 16 | #344 | Strategy or equivalent on the use of artificial intelligence (AI enabled) | Information on a strategy or equivalent on the use of artificial intelligence, AI-enabled, for e-government or the public sector |

## Evidence locus tags

Per FR-129, each question declares where its evidence may come from. Tags below are derived from each indicator's own wording plus its "How?" guidance in the source deck.

| # | Indicator(s) | Locus | Basis |
|---|---|---|---|
| 1 | #010 | `national_portal_only` | Guidance: *"Publish the diagram prominently on the national portal"* |
| 2 | #011 | `national_portal_only` | Wording: *"available on the national portal(s)"* |
| 3 | #012 | `national_portal_only` | The indicator is the presence of links **on** the portal |
| 4 | #014 | `national_portal_only` | Wording: *"available on the national portal"* |
| 5 | #342 | `any_government_domain` | *"Existence of a … strategy"* — commonly on a ministry or digital-agency site |
| 6 | #339 | ⚠️ **needs confirmation** | Wording is content-presence, but guidance says *"Provide a dedicated section"* on the portal while the FOI act itself sits elsewhere |
| 7 | #338 | `any_government_domain` | *"Existence of legislation…"* — normally a parliament or DPA site |
| 8 | #340 | `any_government_domain` | *"Existence of legislation…"* |
| 9 | #337 | ⚠️ **needs confirmation** | *"Information/contact about a National CIO"* — may be on the portal or on a digital-agency site |
| 10 | #345 | `any_government_domain` | *"Existence of legislation…"* |
| 11 | #341 | `any_government_domain` | *"Existence of legislation…"* |
| 12 | #090, #103, #119, #132, #161, #172 | `national_portal_only` | The indicator is the presence of links **on** the portal; guidance references the portal's Ministries/Cabinet section |
| 13 | #091, #104, #120, #133, #162, #173 | `any_government_domain` | Case example is Korea's **ministry of health** policies section — a ministry site, not the portal |
| 14 | #336 | `any_government_domain` | *"Existence of legislation…"* |
| 15 | #343 | `any_government_domain` | *"Information on a cloud strategy"* — commonly a ministry or digital-agency site |
| 16 | #344 | `any_government_domain` | Case example is Switzerland's page on its use of AI |

**Two need your confirmation before the run** — #339 and #337. Both could be argued either way from the source deck, and the choice flips the answer for any country that publishes the artifact off-portal. Everything else is unambiguous from the wording.

Note the split within rows 12 and 13, which look similar but are not: row 12 asks whether the portal *links to* sectoral sites (so the evidence is a link on the portal), while row 13 asks whether sectoral policy *information exists* (so the evidence is on the sectoral site itself).

## Multi-sector rows

Rows 12 and 13 are **not single questions**. Each is one question form applied across six sectors, carrying six distinct indicator IDs:

| Row | Sectors | Indicator IDs |
|---|---|---|
| 12 — sectoral links | Health, Education, Employment/Labor, Social Protection, Environment, Justice | #090, #103, #119, #132, #161, #172 |
| 13 — sectoral policy information | Health, Education, Employment/Labor, Social Protection, Environment, Justice | #091, #104, #120, #133, #162, #173 |

Each sector is separately answerable and separately scored, so treating a row as one unit would collapse six indicators into one answer and lose the per-sector result the index needs. **Modelled as 26 question records, not 16** — with the six sector variants of rows 12 and 13 expanded into individual questions carrying their own indicator ID.

This matters beyond bookkeeping: unit counts, portal-level agreement measures (FR-035), and benchmark accuracy (FR-096) are all computed per question. Expanding at load time keeps every downstream measure consistent with how the index actually consumes the data.

## Characteristics of this set

Properties that shape what the PoC will and will not exercise:

| Property | Consequence |
|---|---|
| **All binary existence checks** — "Existence of…", "Information available on…" | Matches the spec's assumption that items are predominantly binary. The structured answer type is binary throughout; non-binary handling is not exercised. |
| **All publicly reachable** — none requires an account | The authentication-gating path (FR-107–FR-111) is unlikely to trigger on this set. It should still be built, since it costs little here and is load-bearing for the full questionnaire, but the PoC will not validate it against a real gated case. |
| **Several are documents, not page features** — legislation, strategies, policies | Evidence is often a linked PDF rather than a rendered page region. Region-scoped capture (FR-021) needs a defined behaviour for document targets. |
| **Several may live off the national portal** — legislation commonly sits on a parliament or ministry site | Governed per question by the evidence-locus tags above (FR-129). Roughly half this set is `any_government_domain`, so the PoC exercises off-portal evidence heavily — this is not an edge case here, it is the common path. |
| **26 units per country** | At 5 countries × 2 agents ≈ 260 agent runs plus ~260 verification fetches — small enough to run repeatedly while tuning. |

## Unit volume

| Countries | Questions | Agents | Agent runs | Verification fetches |
|---|---|---|---|---|
| 5 | 26 | 2 | 260 | ~260 |

Roughly 1/150th of a production cycle, which makes the full pipeline — including validation, verification, and adjudication retries — affordable to run end to end many times over.
