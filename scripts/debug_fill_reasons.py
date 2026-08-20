"""Summarizes why the assessor did NOT fill in a Yes, across one database's
assessor_agent_runs table, for the 2026-08-20 debugging pass (low yes-rate
triage). Reports, per unique question (last run wins if there were
confidence-gate retries):

  - overall answer distribution (True / False / None)
  - for non-True answers: portal_unreachable / auth_boundary / genuine
    content-based No, broken out by the model's own `fill_gap_reason`
  - which models actually served the run

Usage:
    python scripts/debug_fill_reasons.py data/denmark_v2.db
"""

from __future__ import annotations

import collections
import json
import pathlib
import sqlite3
import sys


def main(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM assessor_agent_runs ORDER BY created_at").fetchall()

    by_question: dict[str, dict] = {}
    for r in rows:
        by_question[r["question_id"]] = json.loads(r["data"])

    total = len(by_question)
    print(f"DB: {db_path}")
    print(f"Unique questions with at least one assessor run: {total}")
    if total == 0:
        return

    answers = collections.Counter(str(d.get("answer")) for d in by_question.values())
    print(f"\nAnswer distribution: {dict(answers)}")
    yes = answers.get("True", 0)
    print(f"Yes-rate over all attempted: {yes}/{total} = {yes/total:.1%}")

    models = collections.Counter(d.get("model_identity") for d in by_question.values())
    print(f"\nModels that actually served answers: {dict(models)}")

    print("\n--- Why not Yes? (fill_gap_reason on every non-True answer) ---")
    blockers = collections.Counter()
    unreachable = 0
    auth = 0
    link_wrong = 0
    for d in by_question.values():
        if d.get("answer") is True:
            continue
        if d.get("portal_unreachable"):
            unreachable += 1
            continue
        if d.get("auth_boundary_observed"):
            auth += 1
            continue
        if d.get("link_likely_wrong"):
            link_wrong += 1
        reason = (d.get("fill_gap_reason") or "").strip()
        blockers[reason or "(no fill_gap_reason recorded -- pre-dates this field)"] += 1

    print(f"portal_unreachable: {unreachable}")
    print(f"auth_boundary: {auth}")
    print(f"link_likely_wrong (model flagged the resolved link itself as wrong): {link_wrong}")
    print("content-level blockers (grouped verbatim -- eyeball for recurring phrasing):")
    for reason, count in blockers.most_common(30):
        print(f"  [{count:>3}] {reason}")

    print("\n--- Evidence relocation (search_by_text) on non-True answers ---")
    located = collections.Counter()
    for d in by_question.values():
        if d.get("answer") is True or d.get("portal_unreachable") or d.get("auth_boundary_observed"):
            continue
        if not d.get("raw_evidence_quote"):
            located["no quote recorded (pre-dates this field)"] += 1
        elif d.get("evidence_located"):
            located["located"] += 1
        else:
            located["quote provided but NOT locatable on the live page"] += 1
    for k, count in located.most_common():
        print(f"  [{count:>3}] {k}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {pathlib.Path(__file__).name} <path-to-db>")
        raise SystemExit(1)
    main(sys.argv[1])
