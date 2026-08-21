"""Script to purge old USA run data from data/ and data/captures/."""

import glob
import os
import shutil
import sqlite3

def clean_usa_runs():
    # 1. Remove USA databases
    for f in glob.glob("data/usa_sample*.db"):
        try:
            os.remove(f)
            print(f"Removed DB: {f}")
        except Exception as e:
            print(f"Error removing {f}: {e}")

    # 2. Remove USA capture dirs
    for d in glob.glob("data/captures/usa-*"):
        try:
            shutil.rmtree(d)
            print(f"Removed Capture Dir: {d}")
        except Exception as e:
            print(f"Error removing {d}: {e}")

    # 3. Clean USA records from data/aiq.db if any
    if os.path.exists("data/aiq.db"):
        conn = sqlite3.connect("data/aiq.db")
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        for table in tables:
            try:
                cols = [col[1] for col in cursor.execute(f"PRAGMA table_info({table})").fetchall()]
                for c in ["cycle_id", "session_id", "country_id"]:
                    if c in cols:
                        cursor.execute(f"DELETE FROM {table} WHERE {c} LIKE ? OR {c} LIKE ?", ("%usa%", "%US%"))
            except Exception as e:
                pass
        conn.commit()
        conn.close()
        print("Cleaned USA references from aiq.db")

if __name__ == "__main__":
    clean_usa_runs()
