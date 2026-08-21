"""Reset a benchmark database to a clean, re-runnable state.

Deletes every *run-scoped* row (sessions, units, agent runs, validations,
prefills, evidence, telemetry) while preserving the *seed* rows that define
what is being measured -- the survey cycle, the questions, the target portal,
the benchmark set, and the ground-truth answers.

This matters because `process_unit` short-circuits on a unit already in a
terminal state ("already terminal"). Leftover units from an earlier run make a
fresh run silently skip work and report stale numbers.

Deleting the whole .db file would also destroy the 25 seeded questions and the
31 ground-truth rows, forcing a re-seed; this keeps them.

Usage:
    python scripts/reset_runs.py [--db data/usa_sample.db] [--yes]
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sqlite3
import sys
from datetime import datetime

# Rows that define WHAT is measured -- never deleted.
SEED_TABLES = {
    "survey_cycles",
    "questions",
    "question_revisions",
    "target_portals",
    "benchmark_sets",
    "ground_truth_answers",
    "prior_survey_links",
    "msq_link_candidates",
    "msq_documents",
}


def reset(db_path: str, assume_yes: bool = False) -> int:
    path = pathlib.Path(db_path)
    if not path.exists():
        print(f"No such database: {path}")
        return 1

    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]

    run_tables = sorted(t for t in tables if t not in SEED_TABLES)
    counts = {t: cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in run_tables}
    doomed = {t: n for t, n in counts.items() if n}

    if not doomed:
        print(f"{path.name}: already clean -- no run rows to remove.")
        conn.close()
        return 0

    print(f"{path.name}: will delete {sum(doomed.values())} run rows across {len(doomed)} tables")
    for t, n in sorted(doomed.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>7}  {t}")
    print("  preserved:", ", ".join(
        f"{t}={cur.execute(f'SELECT COUNT(*) FROM \"{t}\"').fetchone()[0]}"
        for t in sorted(SEED_TABLES) if t in tables
    ))

    if not assume_yes:
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply != "y":
            print("Aborted.")
            conn.close()
            return 1

    backup = path.with_suffix(f".{datetime.now():%Y%m%d_%H%M%S}.bak")
    shutil.copy2(path, backup)
    print(f"Backup: {backup.name}")

    for t in doomed:
        cur.execute(f'DELETE FROM "{t}"')
    conn.commit()
    cur.execute("VACUUM")
    conn.close()
    print(f"Reset complete -- {path.name} is ready for a fresh run.")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="data/usa_sample.db")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    a = p.parse_args()
    sys.exit(reset(a.db, a.yes))
