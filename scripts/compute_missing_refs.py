"""
T004: Compute set difference between 25 question ids in usa-sample-2026 cycle
and the 13 ids already in data/benchmark/reference_links_us.json.
Write missing ids to specs/010-recall-recovery/missing-references.md.
"""
import sqlite3
import json
from pathlib import Path

# Read question ids from usa_sample.db for cycle usa-sample-2026
conn = sqlite3.connect("data/usa_sample.db")
cur = conn.cursor()

cur.execute("""
    SELECT q.data
    FROM questions q
    JOIN survey_cycles c ON q.cycle_id = c.cycle_id
    WHERE c.cycle_id = 'usa-sample-2026'
""")
rows = cur.fetchall()
conn.close()

sample_ids = set()
for (data_str,) in rows:
    data = json.loads(data_str) if data_str else {}
    # question_id is like "usa-sample-2026:CP-030" -> we want "CP-030"
    qid = data.get("question_id", data.get("id", ""))
    # strip the cycle prefix if present
    if ":" in qid:
        qid = qid.split(":", 1)[1]
    # also try indicator_id
    indicator = data.get("indicator_id", "")
    if qid:
        sample_ids.add(qid)
    if indicator:
        sample_ids.add(indicator)

print(f"Sample IDs ({len(sample_ids)}):", sorted(sample_ids))

# Read existing reference ids
ref_path = Path("data/benchmark/reference_links_us.json")
ref_data = json.loads(ref_path.read_text(encoding="utf-8"))
ref_ids = {e["question_id"] for e in ref_data["entries"]}
print(f"Reference IDs ({len(ref_ids)}):", sorted(ref_ids))

missing = sample_ids - ref_ids
print(f"\nMissing ({len(missing)}):", sorted(missing))
