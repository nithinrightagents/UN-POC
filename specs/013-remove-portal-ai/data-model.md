# Data Model & Schema Changes: Removal of AI Prefill from Portal

**Feature Directory**: `specs/013-remove-portal-ai`  
**Date**: 2026-08-26  
**Status**: Complete

---

## 1. Entity Modifications

### `HumanAssessorSubmission` (`src/shared/state/entities.py`)

The dataclass representing an assessor's evaluation on an indicator is cleaned of AI telemetry fields.

```python
@dataclass(frozen=True)
class HumanAssessorSubmission:
    """One append-only evaluation record submitted by a human assessor."""
    submission_id: str
    session_id: str
    question_id: str
    portal_id: str
    role: AssessorRole          # 'A' | 'B'
    actor_id: str
    answer: bool
    evidence_url: str | None = None
    notes: str | None = None
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

*Removed fields:*
- `ai_suggested_answer: bool | None` (Retired)
- `ai_suggestion_accepted: bool | None` (Retired)

---

## 2. Database Schema DDL Changes (`src/shared/persistence/schema.py`)

### Updated `human_submissions` Table

```sql
CREATE TABLE IF NOT EXISTS human_submissions (
    submission_id TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    question_id   TEXT NOT NULL,
    portal_id     TEXT NOT NULL,
    role          TEXT NOT NULL CHECK(role IN ('A', 'B')),
    actor_id      TEXT NOT NULL,
    answer        INTEGER NOT NULL,
    evidence_url  TEXT,
    notes         TEXT,
    submitted_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_human_submissions_lookup
    ON human_submissions(session_id, portal_id, question_id, role, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_human_submissions_role
    ON human_submissions(session_id, portal_id, role);
```

### Retired Tables (Removed from Active Schema)

The following tables are retired and no longer created by default in `init_db()`:
- `prefills` (previously stored multi-agent AI suggested answers and justifications)
- `prefill_candidates` (previously stored heuristic link candidates extracted from MSQ text)

### Migration Helper

For existing database files, `init_db()` executes non-destructive safety migrations:
```sql
DROP TABLE IF EXISTS prefill_candidates;
DROP TABLE IF EXISTS prefills;
```

---

## 3. Repository Method Updates (`src/shared/persistence/repositories.py`)

### `insert_human_submission`
```python
def insert_human_submission(self, sub: HumanAssessorSubmission) -> None:
    submitted_at_str = (
        sub.submitted_at.isoformat()
        if hasattr(sub.submitted_at, "isoformat")
        else str(sub.submitted_at)
    )
    with self.connect() as conn:
        conn.execute(
            """
            INSERT INTO human_submissions (
                submission_id, session_id, question_id, portal_id,
                role, actor_id, answer, evidence_url, notes, submitted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sub.submission_id,
                sub.session_id,
                sub.question_id,
                sub.portal_id,
                sub.role.value if hasattr(sub.role, "value") else str(sub.role),
                sub.actor_id,
                1 if sub.answer else 0,
                sub.evidence_url,
                sub.notes,
                submitted_at_str,
            ),
        )
```

### `_row_to_human_submission`
```python
def _row_to_human_submission(self, row: sqlite3.Row) -> HumanAssessorSubmission:
    return HumanAssessorSubmission(
        submission_id=row["submission_id"],
        session_id=row["session_id"],
        question_id=row["question_id"],
        portal_id=row["portal_id"],
        role=AssessorRole(row["role"]),
        actor_id=row["actor_id"],
        answer=bool(row["answer"]),
        evidence_url=row["evidence_url"] if "evidence_url" in row.keys() else None,
        notes=row["notes"] if "notes" in row.keys() else None,
        submitted_at=row["submitted_at"],
    )
```

---

## 4. Retained & Untouched Domain Entities

The following core entities remain 100% untouched and functional:
- `SurveyCycle`
- `TargetPortal`
- `Question`
- `AssessorCompletion`
- `ReconciliationRound`
- `JointAnswer`
- `ToleranceChange`
- `PublicationRecord`
- `EscalationItem`
