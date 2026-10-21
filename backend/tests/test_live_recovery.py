from review_helpers import accepted_review, rejected_review, unchanged_patch
from sqlalchemy import select
from fastapi.testclient import TestClient
from app.agent import model_grounds, restore_citations, validate_insight
from app.config import settings
from app.context import company_context
from app.main import app
from app.models import Company, Event, Link, LlmAllowance, Run
from app.schemas import Claim, Insight
from app.worker import process_one


def test_company_features_and_publication_date_are_valid_but_invented_numbers_are_not():
    context = {'features': {'workers': {'value': 25, 'source': 'case.csv, row 2'}}}
    evidence = [{'id': 'source', 'kind': 'bank', 'excerpt': 'Банк ожидает замедление спроса.',
        'published_at': '2026-09-11T00:00:00Z'}]
    insight = Insight(headline='Проверка', facts=[Claim(text='В компании 25 сотрудников.', feature_keys=['workers'])],
        bank_view=[Claim(text='В материале от 11.09.2026 банк ожидает замедление спроса.', evidence_ids=['source'])],
        impact=[Claim(text='Если спрос замедлится, требуется проверить план.', evidence_ids=['source'], assumption=True)])
    assert not validate_insight(insight, evidence, context)
    insight.facts[0].text = 'В компании 250 сотрудников.'
    assert any('число отсутствует' in issue for issue in validate_insight(insight, evidence, context))
    insight.facts[0].feature_keys = ['unknown']
    assert any('неизвестный признак' in issue for issue in validate_insight(insight, evidence, context))


def test_self_payments_do_not_create_external_concentration(client, db):
    company = db.get(Company, 'demo-metal')
    before = company_context(db, company)
    db.add(Link(id='self', kind='payment', source_id=company.id, target_id=company.id, amount=999999999, count=1))
    db.commit()
    after = company_context(db, company)
    for field in ['counterparty_count', 'outgoing_concentration']:
        assert after['features'][field] == before['features'][field]
    assert all(c['id'] != company.id for c in after['counterparties'])
    assert after['payment_summary']['self_payments'] == 999999999


def test_short_citations_round_trip_without_accepting_unknown_references():
    evidence = [{'id': 'opaque-source-uuid:5', 'document_id': 'doc-uuid', 'kind': 'news', 'excerpt': 'Событие'}]
    sources, aliases = model_grounds(evidence)
    assert sources[0]['id'] == 'E1' and 'document_id' not in sources[0]
    draft = Insight(headline='Событие', impact=[Claim(text='Условный сценарий', evidence_ids=['E1', 'E99'], assumption=True)])
    restored = restore_citations(draft, aliases)
    assert draft.impact[0].evidence_ids == ['E1', 'E99']
    assert restored.impact[0].evidence_ids == ['opaque-source-uuid:5', 'E99']
    assert any('неизвестная ссылка' in issue for issue in validate_insight(restored, evidence, {'features': {}}))


def test_invalid_citation_skips_paid_review(client, db, monkeypatch):
    from app import agent
    parent_id, _ = rejected_run(client, db)
    calls = []
    def fake_model(system, payload, **kwargs):
        calls.append(system)
        if 'allowed_edits' in payload:
            return unchanged_patch(payload)
        return {'headline': payload['event'], 'impact': [{'text': 'Условный сценарий', 'evidence_ids': ['E99'], 'assumption': True}]}
    monkeypatch.setattr(settings(), 'demo_mode', False)
    monkeypatch.setattr(agent, 'complete_json', fake_model)
    run_id = client.post('/api/insights/'+parent_id+'/retry').json()['run_id']
    process_one()
    result = client.get('/api/runs/'+run_id).json()
    assert result['result']['verification'] == 'insufficient' and len(calls) == 2
    assert not result['result']['impact']


def rejected_run(client, db):
    event = db.scalar(select(Event).where(Event.title.like('Ставка%')))
    body = {'company_id':'demo-metal', 'event_id':event.id, 'role':'CFO'}
    run_id = client.post('/api/analyses', json=body).json()['run_id']
    process_one()
    db.expire_all()
    run = db.get(Run, run_id)
    run.result = {**run.result, 'verification':'insufficient', 'limitations':['Проверить основания']}
    db.commit()
    return run_id, body


def test_repair_uses_two_calls_and_cache_keeps_result(client, db, monkeypatch):
    from app import agent
    parent_id, body = rejected_run(client, db)
    parent = db.get(Run, parent_id)
    parent.result = {**parent.result, 'context_features':{'old_private_value':'stale-context-must-not-be-used'}}
    db.commit()
    calls = []
    def fake_model(system, payload, **kwargs):
        calls.append(system)
        assert 'stale-context-must-not-be-used' not in str(payload)
        if 'Проверь, подтверждаются' in system:
            return accepted_review(payload)
        if 'allowed_edits' in payload:
            return unchanged_patch(payload)
        assert 'output_schema' in payload
        assert payload['previous'] is None
        e = next(e for e in payload['evidence'] if e['kind'] == 'news')
        return {'headline': payload['event'], 'facts':[{'text':e['excerpt'], 'evidence_ids':[e['id']]}],
            'impact':[{'text':'Если предстоит рефинансирование, проверьте условия.', 'evidence_ids':[e['id']],
                'feature_keys':['CL_PRODUCT_LOA_MARK'], 'assumption':True}]}
    monkeypatch.setattr(settings(), 'demo_mode', False)
    monkeypatch.setattr(agent, 'complete_json', fake_model)
    with TestClient(app, headers={'X-Alfa-Request':'1'}) as viewer:
        viewer.post('/api/auth/login', json={'username':'viewer','password':'demo-alfa-2026'})
        assert viewer.post('/api/insights/'+parent_id+'/retry').status_code == 404
    response = client.post('/api/insights/'+parent_id+'/retry')
    assert response.status_code == 202
    run_id = response.json()['run_id']
    process_one()
    result = client.get('/api/runs/'+run_id).json()
    assert result['result']['verification'] == 'checked' and len(calls) == 2
    cached = client.post('/api/analyses', json=body).json()
    assert cached == {'run_id':run_id, 'cached':True}
    assert client.post('/api/insights/'+run_id+'/retry').status_code == 409


def test_repair_fails_before_call_when_only_one_slot_remains(client, db, monkeypatch):
    parent_id, _ = rejected_run(client, db)
    db.add(LlmAllowance(key='initial-trial', requests=19, spent=1)); db.commit()
    monkeypatch.setattr(settings(), 'demo_mode', False)
    assert client.post('/api/insights/'+parent_id+'/retry').status_code == 429


def test_review_sees_features_and_correction_sees_current_draft(client, db, monkeypatch):
    from app import agent
    parent_id, _ = rejected_run(client, db)
    drafts = []
    reviews = []
    def fake_model(system, payload, **kwargs):
        if 'Проверь, подтверждаются' in system:
            assert payload['company_grounds']['impact.0']['CL_PRODUCT_LOA_MARK']['value'] is True
            reviews.append(payload)
            return rejected_review(payload) if len(reviews) == 1 else accepted_review(payload)
        drafts.append(payload)
        if 'allowed_edits' in payload:
            return unchanged_patch(payload)
        e = payload['evidence'][0]
        if 'allowed_edits' in payload:
            return unchanged_patch(payload)
        return {'headline': payload['event'], 'impact': [{'text': 'Если предстоит рефинансирование, уточните условия.',
            'evidence_ids': [e['id']], 'feature_keys': ['CL_PRODUCT_LOA_MARK'], 'assumption': True}]}
    monkeypatch.setattr(settings(), 'demo_mode', False)
    monkeypatch.setattr(agent, 'complete_json', fake_model)
    run_id = client.post('/api/insights/'+parent_id+'/retry').json()['run_id']
    process_one()
    result = client.get('/api/runs/'+run_id).json()
    assert result['result']['verification'] == 'checked'
    assert len(drafts) == len(reviews) == 2
    assert drafts[0]['draft_to_correct'] is None
    assert drafts[1]['draft_to_correct']['impact'][0]['text'].startswith('Если предстоит')
    assert drafts[1]['allowed_edits'] == ['impact.0']
    assert 'Уточнить условие рефинансирования' in drafts[1]['corrections'][0]


def test_missing_review_verdict_never_passes(client, db, monkeypatch):
    from app import agent
    parent_id, _ = rejected_run(client, db)
    def fake_model(system, payload, **kwargs):
        if 'Проверь, подтверждаются' in system:
            return {}
        if 'allowed_edits' in payload:
            return unchanged_patch(payload)
        return {'headline': payload['event'], 'impact': [{'text': 'Если предстоит рефинансирование, проверьте условия.',
            'feature_keys': ['CL_PRODUCT_LOA_MARK'], 'assumption': True}]}
    monkeypatch.setattr(settings(), 'demo_mode', False)
    monkeypatch.setattr(agent, 'complete_json', fake_model)
    run_id = client.post('/api/insights/'+parent_id+'/retry').json()['run_id']
    process_one()
    assert client.get('/api/runs/'+run_id).json()['result']['verification'] == 'insufficient'


def test_one_remaining_request_does_not_start_incomplete_live_analysis(client, db, monkeypatch):
    db.add(LlmAllowance(key='initial-trial', requests=39, spent=15)); db.commit()
    monkeypatch.setattr(settings(), 'llm_request_limit', 40)
    monkeypatch.setattr(settings(), 'demo_mode', False)
    event = db.scalar(select(Event).where(Event.title.like('Ставка%')))
    assert client.post('/api/analyses', json={'company_id':'demo-metal', 'event_id':event.id, 'role':'CFO'}).status_code == 429
    assert not db.scalars(select(Run)).all()
