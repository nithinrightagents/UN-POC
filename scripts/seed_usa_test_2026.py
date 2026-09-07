import sqlite3
import json

def seed_usa_test_cycle():
    ref = json.load(open('data/benchmark/reference_links_us.json', encoding='utf-8'))
    qids = set(e['question_id'] for e in ref['entries'])

    from shared.persistence.repositories import Repository
    from shared.state.entities import SurveyCycle, TargetPortal, ProjectType, Question
    from shared.persistence.schema import connect

    conn_src = sqlite3.connect('data/usa_sample.db')
    conn_src.row_factory = sqlite3.Row
    repo_src = Repository(conn_src)

    conn_dst = connect('data/aiq.db')
    repo_dst = Repository(conn_dst)

    # Ensure survey cycle
    if not repo_dst.get_cycle('usa-test-2026'):
        cycle = SurveyCycle(
            cycle_id='usa-test-2026',
            name='USA Link Resolution Diagnostic Cycle',
            questionnaire_ref='Reference Set',
            country_set=['US'],
            project_type=ProjectType.NATIONAL_OSI,
        )
        repo_dst.insert_cycle(cycle)

    # Ensure target portal
    portals = repo_dst.list_portals('usa-test-2026')
    if not portals:
        portal = TargetPortal(
            portal_id='portal-us-test',
            cycle_id='usa-test-2026',
            country_id='US',
            resolved_url='https://www.usa.gov',
            unit_type='country',
            display_name='United States',
        )
        repo_dst.insert_portal(portal)

    import dataclasses
    # Copy questions
    copied = 0
    src_questions = repo_src.list_questions('test_egov_USA')
    for q in src_questions:
        qid_full = q.question_id
        bare_qid = qid_full.split(':', 1)[-1]
        if bare_qid in qids:
            new_qid = f'usa-test-2026:{bare_qid}'
            q_copy = dataclasses.replace(q, question_id=new_qid, cycle_id='usa-test-2026')
            repo_dst.insert_question(q_copy)
            copied += 1

    print(f"Successfully seeded usa-test-2026 with {copied} questions.")

if __name__ == '__main__':
    seed_usa_test_cycle()
