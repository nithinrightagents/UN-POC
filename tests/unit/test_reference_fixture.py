import json
import sqlite3
from pathlib import Path


def _load_sample_question_ids() -> set:
    """Read the 25-question sample IDs from usa_sample.db for cycle usa-sample-2026."""
    db_path = Path("data/usa_sample.db")
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT data FROM questions WHERE cycle_id = 'usa-sample-2026'")
        ids = set()
        for (data_str,) in cur.fetchall():
            data = json.loads(data_str) if data_str else {}
            qid = data.get("question_id", "")
            if ":" in qid:
                qid = qid.split(":", 1)[1]
            if qid:
                ids.add(qid)
        return ids
    finally:
        conn.close()


def test_reference_fixture_structure():
    fixture_path = Path("data/benchmark/reference_links_us.json")
    assert fixture_path.exists(), "Reference fixture file data/benchmark/reference_links_us.json must exist"

    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "entries" in data
    entries = data["entries"]

    # T008: Assert coverage of every id in the 25-question sample so that a future
    # sample change that outruns the reference set fails loudly instead of silently
    # scoring a subset.
    sample_ids = _load_sample_question_ids()
    if sample_ids:
        fixture_question_ids = {e["question_id"] for e in entries}
        missing = sample_ids - fixture_question_ids
        assert not missing, (
            f"Reference fixture is missing entries for {len(missing)} question(s) "
            f"from the usa-sample-2026 cycle: {sorted(missing)}. "
            "Run T005 to add the missing entries."
        )

    found_indicators = set()
    by_ind = {}
    for entry in entries:
        assert "question_id" in entry
        assert "country_id" in entry
        assert entry["country_id"] == "US"
        assert "expected_answer" in entry
        assert isinstance(entry["expected_answer"], bool)
        assert "reference_url" in entry
        assert "no_valid_link" in entry
        assert isinstance(entry["no_valid_link"], bool)
        assert "accepted_alternatives" in entry
        assert isinstance(entry["accepted_alternatives"], list)
        assert "confidence" in entry
        assert entry["confidence"] in ("authoritative", "provisional")
        assert "verified_on" in entry
        assert "origin" in entry
        assert "note" in entry

        ind = entry.get("indicator_id")
        found_indicators.add(ind)
        by_ind[ind] = entry

    # Verify known specific constraints that must remain true
    entry_054 = by_ind.get("#054")
    if entry_054:
        assert entry_054["confidence"] == "provisional"
        assert entry_054["no_valid_link"] is True
        assert "subnationally" in entry_054["note"].lower()

    entry_339 = by_ind.get("#339")
    if entry_339:
        assert entry_339["confidence"] == "provisional"
        assert "thin generic page" in entry_339["note"].lower() or "generic" in entry_339["note"].lower()


def test_minimal_reference_fixture():
    min_path = Path("tests/fixtures/reference/minimal.json")
    assert min_path.exists()
    with open(min_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "entries" in data
    assert len(data["entries"]) == 3
    confidences = {e["confidence"] for e in data["entries"]}
    assert "authoritative" in confidences
    assert "provisional" in confidences
    assert any(e["no_valid_link"] is True for e in data["entries"])
