"""Extract and format results from USA 25-question run."""

import json
import sqlite3
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

conn = sqlite3.connect("data/usa_sample.db")
conn.row_factory = sqlite3.Row

# Get all questions
questions_by_id = {}
for r in conn.execute("SELECT * FROM questions").fetchall():
    d = json.loads(r["data"])
    questions_by_id[r["question_id"]] = d

# Get all units
units_by_qid = {}
for r in conn.execute("SELECT * FROM units").fetchall():
    d = json.loads(r["data"])
    units_by_qid[r["question_id"]] = (r["state"], d)

# Get all assessor runs
assessor_runs = conn.execute("SELECT * FROM assessor_agent_runs ORDER BY created_at ASC").fetchall()
runs_by_qid = {}
for r in assessor_runs:
    d = json.loads(r["data"])
    runs_by_qid.setdefault(r["question_id"], []).append(d)

# Get all prefills
prefills_by_qid = {}
for r in conn.execute("SELECT * FROM prefills").fetchall():
    d = json.loads(r["data"])
    prefills_by_qid[r["question_id"]] = d

# Get adjudications
adj_by_qid = {}
for r in conn.execute("SELECT * FROM adjudication_results").fetchall():
    d = json.loads(r["data"])
    adj_by_qid[r["question_id"]] = d

results = []
for qid, q_info in questions_by_id.items():
    unit_state, unit_data = units_by_qid.get(qid, ("unknown", {}))
    prefill = prefills_by_qid.get(qid, {})
    runs = runs_by_qid.get(qid, [])
    adj = adj_by_qid.get(qid, {})

    # Extract resolved URL from runs or unit
    resolved_urls = [r.get("resolved_url") for r in runs if r.get("resolved_url")]
    first_url = resolved_urls[0] if resolved_urls else unit_data.get("resolved_url")
    evidence_urls = [r.get("evidence", {}).get("resolved_url") for r in runs if r.get("evidence")]
    final_evidence_url = evidence_urls[-1] if evidence_urls else (prefill.get("evidence", {}) or {}).get("resolved_url")

    ans = prefill.get("answer")
    conf = prefill.get("confidence")
    justification = prefill.get("justification") or ""
    fill_gap_reason = prefill.get("fill_gap_reason")
    if not fill_gap_reason and runs:
        fill_gap_reason = runs[-1].get("fill_gap_reason")

    res = {
        "question_id": qid,
        "indicator_id": q_info.get("indicator_id", "N/A"),
        "title": q_info.get("title", ""),
        "text": q_info.get("text", ""),
        "what": q_info.get("what", ""),
        "evidence_locus": q_info.get("evidence_locus", ""),
        "module": q_info.get("question_class", ""),
        "unit_state": unit_state,
        "answer": ans,
        "confidence": conf,
        "justification": justification,
        "fill_gap_reason": fill_gap_reason,
        "resolved_url": first_url or final_evidence_url,
        "all_resolved_urls": list(dict.fromkeys(resolved_urls)),
        "runs_count": len(runs),
        "assessor_outputs": [
            {
                "answer": r.get("answer"),
                "confidence": r.get("confidence"),
                "justification": r.get("justification"),
                "fill_gap_reason": r.get("fill_gap_reason"),
                "resolved_url": r.get("resolved_url"),
                "link_likely_wrong": r.get("link_likely_wrong"),
            }
            for r in runs
        ],
    }
    results.append(res)

print("\n======================= USA 25-QUESTION RUN RESULTS =======================")
yes_count = sum(1 for r in results if r["answer"] is True)
no_count = sum(1 for r in results if r["answer"] is False)
no_sugg_count = sum(1 for r in results if r["answer"] is None)

print(f"Total: {len(results)} | YES: {yes_count} | NO: {no_count} | NO SUGGESTION: {no_sugg_count}")
print("===========================================================================\n")

for i, res in enumerate(results, 1):
    ans_str = "YES" if res["answer"] is True else ("NO" if res["answer"] is False else "NO SUGGESTION")
    print(f"{i:2d}. [{res['indicator_id']}] {res['title']}")
    print(f"    State: {res['unit_state']} | Answer: {ans_str} | Conf: {res['confidence']}% | Locus: {res['evidence_locus']}")
    print(f"    Resolved URL: {res['resolved_url']}")
    if res["fill_gap_reason"]:
        print(f"    Fill Gap Reason: {res['fill_gap_reason']}")
    if res["justification"]:
        j_snippet = (res['justification'][:140] + "...") if len(res['justification']) > 140 else res['justification']
        print(f"    Justification: {j_snippet}")
    print()

# Save to JSON
with open("data/usa_25q_extracted_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("Saved extracted results to data/usa_25q_extracted_results.json")
