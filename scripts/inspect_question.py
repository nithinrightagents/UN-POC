"""Inspect question data structure in the DB."""
import sqlite3, json

conn = sqlite3.connect("data/usa_sample.db")
cur = conn.cursor()
cur.execute("SELECT data FROM questions WHERE cycle_id = 'usa-sample-2026' LIMIT 3")
for (data_str,) in cur.fetchall():
    d = json.loads(data_str)
    print(json.dumps(d, indent=2))
    print("---")
conn.close()
