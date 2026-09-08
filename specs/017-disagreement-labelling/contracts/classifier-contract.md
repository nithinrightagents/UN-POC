# Contract: The Classifier

**Module**: `src/portal/label_classifier.py` (new)
**Requirements**: FR-DL-033 to FR-DL-039, FR-DL-050, FR-DL-051, FR-DL-056
**Model boundary**: `core.llm_factory.ModelProvider.generate` — the sole entry point, unchanged

---

## 1. Interface

```python
LABEL_PROMPT_VERSION = "dl-1"

@dataclass(frozen=True)
class ClassifierInput:
    indicator_text: str
    positions: tuple[PositionView, PositionView]    # content-ordered, role-free
    interval_seconds: int | None

@dataclass(frozen=True)
class PositionView:
    answer: bool
    evidence_url: str | None
    notes: str | None
    accepted_ai_suggestion: bool | None

@dataclass(frozen=True)
class ClassifierResult:
    label: DisagreementLabel               # one of CLASSIFIER_LABELS
    stated_reason: str
    notes_contradict: tuple[bool, bool]    # keyed to positions[0], positions[1]
    model_identity: str
    input_digest: str
    input_tokens: int
    output_tokens: int

async def classify(provider, settings, payload: ClassifierInput) -> ClassifierResult
```

`classify` raises on provider failure and on an unusable response. The caller turns either into one `labelling_attempts` row — the classifier itself has no persistence and no retry loop.

---

## 2. Building the input

`PositionView` is assembled from `HumanAssessorSubmission` and **nothing else**:

| Field | Source |
|---|---|
| `answer` | `submission.answer` |
| `evidence_url` | `submission.evidence_url` |
| `notes` | `submission.notes` |
| `accepted_ai_suggestion` | `submission.ai_suggestion_accepted` |

`ai_suggested_answer` is on the same row and is **not** read. `Prefill` is not queried at all — the module does not import it, which is a stronger guarantee than remembering not to pass it (D3, FR-DL-037).

**Ordering** is by `(evidence_url or "", notes or "")`, ascending. Role never participates, so the model cannot learn from position which assessor it is reading (FR-DL-038, R7). The caller keeps `order[i] -> role` to map the response back.

**Notes are sent verbatim.** No redaction, truncation, or transformation — the position recorded in A9 and in the spec's Known Limitations, stated rather than mitigated.

---

## 3. The digest

```python
input_digest = sha256(json.dumps(payload_dict, sort_keys=True,
                                 separators=(",", ":"),
                                 ensure_ascii=False).encode("utf-8")).hexdigest()
```

Over the canonical rendering including `prompt_version`, so a changed instruction produces a different digest for identical submissions. This is the artefact FR-DL-056 relies on: a stored label is attributable to the exact content the classifier received, and to no other.

---

## 4. Response schema

Passed to `generate(response_schema=...)`, which sets `response_mime_type="application/json"` ([llm_factory.py:152](../../../src/core/llm_factory.py#L152)):

```json
{
  "type": "object",
  "properties": {
    "label": {"type": "string",
              "enum": ["one_blocked", "different_content",
                       "different_judgement", "not_enough_notes"]},
    "reason": {"type": "string"},
    "position_1_notes_contradict_answer": {"type": "boolean"},
    "position_2_notes_contradict_answer": {"type": "boolean"}
  },
  "required": ["label", "reason",
               "position_1_notes_contradict_answer",
               "position_2_notes_contradict_answer"]
}
```

The enum omits `different_sources` and `one_found_nothing` entirely — the classifier is not offered the two labels the pre-pass owns, so FR-DL-033 is enforced by the schema rather than by an instruction the model may ignore.

**Validation is repeated on parse.** A label outside `CLASSIFIER_LABELS`, a missing key, or unparseable JSON raises, and the caller records the attempt as `schema_rejected`. Schema-constrained decoding is a strong constraint, not a guarantee, and FR-DL-035 says an unrecognised label is never stored.

`temperature=0.0`, per A5 and to keep repeated runs over identical inputs comparable during evaluation.

---

## 5. The instruction

The system instruction is one versioned constant. Its content is a plan-level decision, but four properties are contractual and each has a test:

1. **It never asks which answer is correct.** No sentence in it may admit a verdict as an answer (D2, FR-DL-063).
2. **It defines the three substantive labels by their decision procedure**, in the order the pre-pass leaves them: was one side prevented from reaching the source; did both reach it and describe different content; did both describe the same content and judge it differently.
3. **It makes `not_enough_notes` the required answer under uncertainty**, explicitly rather than as a fallback — FR-DL-034 forbids a best guess among the others, and the ambiguity measure depends on `different_judgement` being clean.
4. **It never refers to Assessor A or B, to roles, or to an AI suggestion's content.**

Changing any word of it requires incrementing `LABEL_PROMPT_VERSION`, because the version is what the audit record names.

---

## 6. Cost recording

The caller records `input_tokens` and `output_tokens` from `ModelResponse` against `CostLedger` with `stage="disagreement_labelling"` and `estimate_cost(model_identity, ...)`. `agent_index` is `None` — this is not an assessor agent, and conflating it with one would corrupt the per-agent comparison the ledger exists for (R9, FR-DL-090).

---

## 7. Testing without a provider

`classify` takes the provider as a parameter, so tests inject a fake exactly as `tests/unit/test_language_support_check.py` and `test_resolve_only.py` already do. The full suite runs offline:

- deterministic pre-pass tests need no provider at all;
- classifier tests use a fake returning canned JSON;
- failure and exhaustion tests use a fake that raises;
- a `NoCallProvider` that fails the test if invoked backs the assertions that GET paths and deterministic labels make no model call (FR-DL-045, SC-009).
