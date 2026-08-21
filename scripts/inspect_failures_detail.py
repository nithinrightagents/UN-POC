import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

data = json.load(open("data/usa_failures_deep_inspection.json", encoding="utf-8"))
for i, f in enumerate(data, 1):
    print(f"{i}. [{f['question_id']}] {f['title']}")
    print(f"   What: {f['what']}")
    print(f"   Expected: {f['expected_answer']} | Delivered: {f['delivered_answer']} (State: {f['unit_state']})")
    print(f"   Landed URL: {f['resolved_url']} (Source: {f['supplying_source']})")
    print(f"   Reference URL: {f['reference_url']}")
    print(f"   Accepted Alternatives: {f['accepted_alternatives']}")
    if f['runs']:
        last_run = f['runs'][-1]
        print(f"   Last Run: ans={last_run['answer']}, conf={last_run['confidence']}, state={last_run['state']}")
        if last_run.get('unreachable_reason'):
            print(f"   Unreachable: {last_run['unreachable_reason']}")
        if last_run.get('justification'):
            print(f"   Justification: {last_run['justification'][:200]}...")
        if last_run.get('fill_gap_reason'):
            print(f"   Fill Gap Reason: {last_run['fill_gap_reason']}")
    if f['validations']:
        print(f"   Validations: {len(f['validations'])} attempts, last quality={f['validations'][-1]['quality_score']}")
        if f['validations'][-1].get('gaps'):
            print(f"   Gaps: {f['validations'][-1]['gaps']}")
    print("-" * 70)
