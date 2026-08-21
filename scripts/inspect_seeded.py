import json
import sqlite3
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


conn = sqlite3.connect("data/usa_sample.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT question_id, data FROM questions").fetchall()
print(f"Total seeded questions: {len(rows)}")
for i, r in enumerate(rows, 1):
    d = json.loads(r["data"])
    qid = r["question_id"]
    ind = d.get("indicator_id", "N/A")
    title = d.get("title", "")
    locus = d.get("evidence_locus", "")
    print(f"{i:2d}. [{ind}] {title} (ID: {qid}, Locus: {locus})")

