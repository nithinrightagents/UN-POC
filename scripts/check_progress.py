import sqlite3

conn = sqlite3.connect("data/usa_sample.db")
try:
    total_units = conn.execute("SELECT COUNT(*) FROM units").fetchone()[0]
    done_units = conn.execute("SELECT COUNT(*) FROM units WHERE state IN ('delivered', 'escalated', 'unassessable')").fetchone()[0]
    runs = conn.execute("SELECT COUNT(*) FROM assessor_agent_runs").fetchone()[0]
    print(f"Units total: {total_units} | Units completed: {done_units} | Assessor runs: {runs}")
except Exception as e:
    print(f"Error checking progress: {e}")
