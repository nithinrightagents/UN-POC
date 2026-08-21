import sqlite3
import json
from datetime import datetime

conn = sqlite3.connect('data/aiq.db')
c = conn.cursor()

# Find how questions in usa-test-2026 look like
c.execute("SELECT question_id, cycle_id, is_custom, data, created_at FROM questions WHERE cycle_id='usa-test-2026' LIMIT 3")
sample_rows = c.fetchall()
print("Sample rows in questions for usa-test-2026:")
for r in sample_rows:
    print(r[0], r[1], r[2], r[4])
    print(" ", r[3][:150])

# Find master definition of SP-108 and EP-092 from msq_indicators.json or questions table
with open('data/questions/msq_indicators.json', 'r', encoding='utf-8') as f:
    master_data = json.load(f)

for q in master_data['questions']:
    ind = q.get('indicator_id')
    qid = q.get('question_id')
    if ind in ('#108', '#092') or qid in ('SP-108', 'EP-092'):
        print(f"\nMaster definition for {qid} ({ind}):")
        new_qid = f"usa-test-2026:{qid}"
        q_copy = dict(q)
        q_copy['question_id'] = new_qid
        q_json = json.dumps(q_copy)
        
        # Check if already in db
        c.execute("SELECT question_id FROM questions WHERE question_id=?", (new_qid,))
        existing = c.fetchone()
        if not existing:
            c.execute(
                "INSERT INTO questions (question_id, cycle_id, is_custom, data, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_qid, 'usa-test-2026', 0, q_json, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            print(f"Inserted {new_qid} into questions for usa-test-2026")
        else:
            print(f"{new_qid} already exists")

conn.commit()

# Verify all 13 indicators in usa-test-2026
c.execute("SELECT question_id, data FROM questions WHERE cycle_id='usa-test-2026'")
all_usa_qs = c.fetchall()
targets = ['#030', '#043', '#045', '#054', '#055', '#092', '#095', '#108', '#336', '#337', '#339', '#340', '#341']
found = set()
for qid, data in all_usa_qs:
    d = json.loads(data)
    ind = d.get('indicator_id')
    if ind in targets:
        found.add(ind)
print("\nAll 13 targets in usa-test-2026:", found == set(targets), f"({len(found)}/13)")
