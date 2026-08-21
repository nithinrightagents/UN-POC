"""Dump per-question detail from usa_sample.db for the baseline report."""
import sqlite3
import json

conn = sqlite3.connect("data/usa_sample.db")
cur = conn.cursor()

# Get units with state and question data
cur.execute("""
    SELECT u.unit_id, u.question_id, u.state, u.data, q.data as qdata
    FROM units u
    JOIN questions q ON u.question_id = q.question_id
    WHERE u.session_id = (
        SELECT session_id FROM assessment_sessions
        ORDER BY created_at DESC LIMIT 1
    )
    ORDER BY u.question_id
""")

rows = cur.fetchall()
print(f"| Question ID | Indicator | State | Resolved URL | prefill_reason |")
print(f"|-------------|-----------|-------|--------------|----------------|")
for unit_id, question_id, state, data_str, qdata_str in rows:
    data = json.loads(data_str) if data_str else {}
    qdata = json.loads(qdata_str) if qdata_str else {}
    indicator_id = qdata.get("indicator_id", qdata.get("id", question_id))
    resolved_url = data.get("resolved_url", data.get("link", ""))
    prefill_reason = data.get("prefill_reason", data.get("no_suggestion_reason", ""))
    print(f"| {question_id} | {indicator_id} | {state} | {resolved_url} | {prefill_reason} |")

conn.close()
