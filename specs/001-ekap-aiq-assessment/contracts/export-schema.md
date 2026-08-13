# Contract: Answer Export

**Satisfies**: FR-101–FR-106, SC-023 | **Data model**: [../data-model.md](../data-model.md) §Answer Export

The handoff boundary. This is how delivered answers leave the system. It does not publish them and computes nothing from them — both are out of scope.

**Format**: newline-delimited JSON, one record per line, plus a separate exclusion report. NDJSON because a cycle's export is ~39,000 records and consumers should be able to stream it without loading the whole file.

## Record schema (FR-102)

```jsonc
{
  "cycle_id": "2026-biennial",
  "country_id": "EE",
  "portal": {
    "resolved_url": "https://eesti.ee",
    "supplying_source": "msq"                  // msq | historical | search
  },
  "question": {
    "question_id": "OSQ-1.14",
    "is_custom": false
  },
  "delivered_answer": true,
  "consensus_confidence": 84,
  "below_acceptance_threshold": false,
  "provenance": "system_proposed",             // system_proposed | human_edited | human_overridden
  "actor_id": "assessor-4417",
  "acted_at": "2026-08-12T14:03:22Z",
  "out_of_set_language_best_effort": false,
  "session_id": "sess-2026-08-11-003",
  "evidence_refs": [
    {
      "artifact_id": "ev-88213",
      "resolved_url": "https://eesti.ee/services",
      "capture_ref": "blob://captures/ev-88213.png",
      "element_reference": { "css_path": "...", "text_hash": "...", "sibling_index": 0 },
      "verified_at": "2026-08-11T09:12:04Z",
      "verifiability_status": "verified"
    }
  ]
}
```

`session_id` is mandatory on every record. It is what makes an exported answer auditable rather than merely readable — from it, a consumer can reconstruct the full history under FR-061.

## Exclusion report (FR-104)

Accompanies every export. Without it a consumer cannot distinguish "this question was answered no" from "this question was never delivered", which is exactly the confusion an index computation must not make.

```jsonc
{
  "cycle_id": "2026-biennial",
  "excluded": [
    { "country_id": "TR", "question_id": "OSQ-2.03", "reason": "requires_authenticated_access" },
    { "country_id": "SS", "question_id": "OSQ-1.01", "reason": "no_usable_url" },
    { "country_id": "KH", "question_id": "OSQ-3.11", "reason": "awaiting_human_review" },
    { "country_id": "LA", "question_id": "OSQ-4.02", "reason": "unresolved_disagreement" }
  ]
}
```

Reasons: `awaiting_human_review`, `unresolved_disagreement`, `portal_discrepancy`, `no_usable_url`, `unreachable_portal`, `unverifiable_target`, `requires_authenticated_access`, `language_declined`.

## Invariants

| # | Invariant | Requirement |
|---|---|---|
| E1 | Only answers in a **delivered** state appear | FR-104 |
| E2 | Zero benchmark-session answers appear, ever | FR-095, SC-021 |
| E3 | Zero answers awaiting review or in unresolved escalation appear | FR-104 |
| E4 | Every excluded question appears in the exclusion report with a reason | FR-104, SC-023 |
| E5 | Export computes no score, rank, or index | FR-105, Out of Scope |
| E6 | Export mutates nothing — no delivered answer, no audit record, no evidence artifact | FR-103, FR-105 |
| E7 | Each export is recorded with time, producing actor, and included record set | FR-106 |

**E2 is enforced twice** — once at the export query and once at the repository boundary (see [../data-model.md](../data-model.md) §Benchmark). A benchmark answer reaching a cycle's delivered results would be a contamination of the official record, so a single point of enforcement is not enough.

**E6 includes evidence.** Producing an export must not delete, detach, or relocate an evidence artifact (FR-103). An export is a read.

## Where this goes

The EKAP Phase 3 package places AIQ as a third source alongside MSQ (government self-report) and OSQ (assessor evaluation), cross-compared in EKAP Process 03. The export is that feed — which is why records carry `session_id` and `evidence_refs` rather than just an answer: the receiving comparison surfaces a variance and a human has to be able to drill into why. See [ekap-integration.md](./ekap-integration.md).
