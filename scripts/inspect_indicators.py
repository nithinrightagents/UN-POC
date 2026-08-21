import sqlite3
import json

conn = sqlite3.connect('data/aiq.db')
c = conn.cursor()
c.execute("SELECT question_id, cycle_id, data FROM questions WHERE cycle_id='usa-test-2026' LIMIT 10")
for qid, cycle_id, data in c.fetchall():
    d = json.loads(data)
    print(f"question_id in table: {qid}, question_id in data: {d.get('question_id')}, indicator_id: {d.get('indicator_id')}")
