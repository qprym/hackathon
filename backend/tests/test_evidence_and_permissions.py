from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import agent
from app.config import settings
from app.db import engine, initialize_development_schema, utcnow
from app.ingestion import digest, import_document
from app.main import app
from app.models import Document, Event, Run, User
from app.schemas import Claim, Insight
from app.worker import process_one


def start(client):
    event = client.get('/api/feed?corpus=synthetic&company_id=demo-metal&role=CFO').json()['items'][0]
    response = client.post('/api/analyses', json={
        'company_id': 'demo-metal', 'event_id': event['id'], 'role': 'CFO'})
    assert response.status_code == 202
    return response.json()['run_id']


def test_inaccessible_profiles_never_enter_live_model_context(client, db, monkeypatch):
    contexts = []

    def fake_model(system, payload, **kwargs):
        # Check every model request, including planning, generation and review.
        assert 'demo-logistics' not in str(payload)
        assert 'demo-retail' not in str(payload)
        assert 'Транспортировка и складское хранение' not in str(payload)
        assert 'Оптовая и розничная торговля' not in str(payload)
        if 'context' in payload:
            contexts.append(payload['context'])
        if 'Извлеки темы' in system:
            return {'topics': [], 'facts': []}
        if 'Составь план' in system:
            return {'tools': ['related_companies'], 'queries': ['ставка кредит']}
        if 'Упорядочь' in system:
            return {'ordered_ids': []}
        if 'Проверь, подтверждаются' in system:
            return {'issues': [], 'search_queries': []}
        return {'headline': payload['event'], 'impact': [{
            'text': 'Проверьте условия кредитных договоров.',
            'evidence_ids': [payload['evidence'][0]['id']],
            'feature_keys': ['CL_PRODUCT_LOA_MARK'], 'assumption': True}]}

    monkeypatch.setattr(settings(), 'demo_mode', False)
    monkeypatch.setattr(agent, 'complete_json', fake_model)
    with TestClient(app, headers={'X-Alfa-Request': '1'}) as viewer:
        viewer.post('/api/auth/login', json={'username': 'viewer', 'password': 'demo-alfa-2026'})
        context = viewer.get('/api/companies/demo-metal/context').json()
        assert all(not c['profile_available'] for c in context['counterparties'])
        assert len({c['id'] for c in context['counterparties']}) == 2
        assert context['payment_summary']['outgoing'] == 10_000_000
        run_id = start(viewer)
        assert process_one()
        result = viewer.get('/api/runs/' + run_id).json()
        assert result['status'] == 'completed'
        assert result['result']['verification'] == 'checked'
        assert contexts and all([g['id'] for g in c['group']] == ['demo-metal'] for c in contexts)
        assert all(c['group'][0]['industry'] == 'Производство металлических изделий' for c in contexts)


def test_revoked_permissions_hide_old_results_and_invalidate_cache(client, db):
    run_id = start(client)
    process_one()
    assert client.get('/api/runs/' + run_id).status_code == 200
    user = db.scalar(select(User).where(User.username == 'demo'))
    user.company_ids = ['demo-metal']
    db.commit()
    assert client.get('/api/runs/' + run_id).status_code == 409
    assert client.post('/api/insights/' + run_id + '/questions', json={'question': 'Какие риски?'}).status_code == 409
    new_id = start(client)
    assert new_id != run_id
    assert process_one()
    assert client.get('/api/runs/' + new_id).json()['status'] == 'completed'


def test_worker_checks_permissions_again_before_processing(client, db, monkeypatch):
    run_id = start(client)
    user = db.scalar(select(User).where(User.username == 'demo'))
    user.company_ids = ['demo-metal']
    db.commit()
    monkeypatch.setattr(settings(), 'demo_mode', False)
    calls = []

    def forbidden_call(*args, **kwargs):
        calls.append(args)
        raise AssertionError('The provider must not receive revoked client data')

    monkeypatch.setattr(agent, 'complete_json', forbidden_call)
    assert process_one()
    db.expire_all()
    assert db.get(Run, run_id).status == 'failed'
    assert not calls


def test_existing_sqlite_database_upgrades_without_losing_runs(client, db):
    run_id = start(client)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE runs DROP COLUMN access_scope'))
    initialize_development_schema()
    initialize_development_schema()
    run = db.get(Run, run_id)
    assert run.status == 'queued' and run.access_scope == []
    assert client.get('/api/runs/' + run_id).status_code == 409


def test_numeric_evidence_compares_full_values():
    evidence = [{'id': 'source', 'kind': 'news', 'excerpt': 'Ставка 10,0%. Объем 1 000 рублей. Динамика −5%.'}]
    for text in ('Ставка 1%.', 'Объем 100 рублей.', 'Динамика 5%.'):
        insight = Insight(headline='Проверка', facts=[Claim(text=text, evidence_ids=['source'])],
                          impact=[Claim(text='Влияние требует проверки.', assumption=True)])
        assert any('число' in issue for issue in agent.validate_insight(insight, evidence, {'features': {}}))
    valid = Insight(headline='Проверка', facts=[Claim(text='Ставка 10.0%, объем 1000 рублей, динамика -5%.', evidence_ids=['source'])],
                    impact=[Claim(text='Влияние требует проверки.', assumption=True)])
    assert not agent.validate_insight(valid, evidence, {'features': {}})


def test_identical_text_keeps_distinct_sources_and_dates(client, db):
    params = dict(title='Платежные сроки изменились',
        content='Синтетический пример: платежные сроки изменились. Для оценки влияния следует проверить договоры и календарь обязательств компании.',
        kind='news', publisher='Первая редакция', published_at=utcnow() - timedelta(days=2),
        url='https://example.org/news/first', synthetic=True)
    first, created = import_document(db, **params)
    assert created
    repeated, created = import_document(db, **params)
    assert not created and repeated.id == first.id
    second, created = import_document(db, **{**params, 'publisher': 'Вторая редакция', 'url': 'https://example.org/news/second'})
    assert created and second.id != first.id
    event = db.scalar(select(Event).where(Event.title == params['title']))
    assert set(event.document_ids) == {first.id, second.id}
    later, created = import_document(db, **{**params, 'published_at': params['published_at'] + timedelta(days=1)})
    assert created and later.id != first.id


def test_legacy_publication_hash_upgrades_without_duplicate(client, db):
    params = dict(title='Проверка старого импорта',
        content='Синтетический материал о сроках платежей и календаре расчетов. Данные о конкретных договорах не предоставлены.',
        kind='news', publisher='Учебная редакция', published_at=utcnow(), synthetic=True)
    original, _ = import_document(db, **params)
    original.content_hash = digest(f"news|True|{params['content']}")
    db.commit()
    repeated, created = import_document(db, **params)
    assert not created and repeated.id == original.id
    assert db.get(Document, original.id).content_hash != digest(f"news|True|{params['content']}")
