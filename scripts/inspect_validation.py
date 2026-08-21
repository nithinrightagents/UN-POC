import sqlite3
import json

conn = sqlite3.connect("data/usa_sample.db")
conn.row_factory = sqlite3.Row

for qid in ["usa-sample-2026:SP-124", "usa-sample-2026:SP-166", "usa-sample-2026:SP-166b"]:
    print(f"\n=== UNIT: {qid} ===")
    unit = conn.execute("SELECT * FROM units WHERE question_id = ?", (qid,)).fetchone()
    if unit:
        print("Unit State:", unit["state"])
        print("Unit Data:", unit["data"])
    
    runs = conn.execute("SELECT * FROM assessor_agent_runs WHERE question_id = ?", (qid,)).fetchall()
    for r in runs:
        print("Run State:", r["state"])
        val = conn.execute("SELECT * FROM validation_results WHERE run_id = ?", (r["run_id"],)).fetchall()
        for v in val:
            print("  Validation passed:", v["passed"], "Data:", v["data"])
