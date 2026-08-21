import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

data = json.load(open("data/usa_25q_extracted_results.json", encoding="utf-8"))
print(f"Total Questions: {len(data)}")
for i, d in enumerate(data, 1):
    ans = "YES" if d["answer"] is True else ("NO" if d["answer"] is False else "NO SUGGESTION")
    print(f"{i:2d}. [{d['indicator_id']}] {d['title']}")
    print(f"    Answer: {ans} | Locus: {d['evidence_locus']} | URL: {d['resolved_url']}")
    if ans in ("NO", "NO SUGGESTION"):
        print(f"    Fill Gap Reason: {d['fill_gap_reason']}")
        print(f"    Justification: {d['justification']}")
    print()
