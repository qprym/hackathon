import copy
import pytest
from fastapi.testclient import TestClient
from app import agent
from app.bank_relevance import SEARCH_VERSION
from app.config import settings
from app.main import app
from app.models import LlmAllowance, Run
from app.worker import process_one
from review_helpers import accepted_review, rejected_review
from test_live_recovery import rejected_run


@pytest.fixture(autouse=True)
def review_budget(monkeypatch):
    for key, value in {'llm_test_limit_rub': 30, 'llm_input_rub_per_million': 1,
                       'llm_output_rub_per_million': 1}.items():
        monkeypatch.setattr(settings(), key, value)


def old_checked_run(client, db):
    run_id, body = rejected_run(client, db)
    parent = db.get(Run, run_id)
    parent.result = {**parent.result, 'verification': 'checked', 'search_version': 'old-version'}
    db.commit()
    return run_id, body


@pytest.mark.parametrize('verdict', ['accepted', 'rejected', 'malformed', 'bad_citation'])
def test_refresh_caps_calls_and_preserves_strict_checks(client, db, monkeypatch, verdict):
    parent_id, body = old_checked_run(client, db)
    old = copy.deepcopy(db.get(Run, parent_id).result)
    db.add(LlmAllowance(key='initial-trial', requests=18, spent=1))
    db.commit()
    calls = []
    def fake(system, payload, **kwargs):
        calls.append(payload)
        if 'Проверь, подтверждаются' in system:
            if verdict == 'malformed':
                return {}
            return rejected_review(payload) if verdict == 'rejected' else accepted_review(payload)
        assert payload['previous'] is None
        assert 'allowed_edits' not in payload
        return {'headline': payload['event'], 'impact': [{
            'text': 'Если предстоит рефинансирование, проверьте условия.',
            'evidence_ids': ['E99'] if verdict == 'bad_citation' else [],
            'feature_keys': ['CL_PRODUCT_LOA_MARK'], 'assumption': True}]}
    monkeypatch.setattr(settings(), 'demo_mode', False)
    monkeypatch.setattr(agent, 'complete_json', fake)
    response = client.post(f'/api/insights/{parent_id}/refresh')
    assert response.status_code == 202
    run_id = response.json()['run_id']
    process_one()
    run = client.get(f'/api/runs/{run_id}').json()
    assert len(calls) == (1 if verdict == 'bad_citation' else 2)
    assert run['result']['verification'] == ('checked' if verdict == 'accepted' else 'insufficient')
    assert run['result']['search_version'] == SEARCH_VERSION and not run['search_outdated']
    assert client.get(f'/api/runs/{parent_id}').json()['result'] == old
    if verdict == 'accepted':
        assert client.post('/api/analyses', json=body).json() == {'run_id': run_id, 'cached': True}
        assert client.post(f'/api/insights/{run_id}/refresh').status_code == 409
    else:
        assert run['result']['impact'] == []


def test_refresh_requires_two_slots_and_authorized_outdated_parent(client, db, monkeypatch):
    parent_id, _ = old_checked_run(client, db)
    with TestClient(app, headers={'X-Alfa-Request': '1'}) as viewer:
        viewer.post('/api/auth/login', json={'username': 'viewer', 'password': 'demo-alfa-2026'})
        assert viewer.post(f'/api/insights/{parent_id}/refresh').status_code == 404
    db.add(LlmAllowance(key='initial-trial', requests=19, spent=1))
    db.commit()
    monkeypatch.setattr(settings(), 'demo_mode', False)
    assert client.post(f'/api/insights/{parent_id}/refresh').status_code == 429
    parent = db.get(Run, parent_id)
    parent.result = {**parent.result, 'verification': 'insufficient'}
    db.commit()
    assert client.post(f'/api/insights/{parent_id}/refresh').status_code == 409


def test_refresh_does_not_repeat_paid_calls_after_worker_restart(client, db, monkeypatch):
    parent_id, _ = old_checked_run(client, db)
    monkeypatch.setattr(settings(), 'demo_mode', False)
    run_id = client.post(f'/api/insights/{parent_id}/refresh').json()['run_id']
    run = db.get(Run, run_id)
    run.attempts = 1
    db.commit()
    process_one()
    result = client.get(f'/api/runs/{run_id}').json()
    assert result['status'] == 'failed' and 'повтор отключён' in result['error']


def test_feedback_remains_visible_without_rewriting_model_result(client, db):
    run_id, _ = old_checked_run(client, db)
    before = client.get(f'/api/runs/{run_id}').json()
    assert before['feedback'] is None
    note = {'category': 'factual_error', 'comment': 'Соблюдение бюджета не доказывает свободный остаток.'}
    assert client.post(f'/api/insights/{run_id}/feedback', json=note).status_code == 200
    after = client.get(f'/api/runs/{run_id}').json()
    assert after['feedback'] == note
    assert after['result'] == before['result']
    with TestClient(app, headers={'X-Alfa-Request': '1'}) as viewer:
        viewer.post('/api/auth/login', json={'username': 'viewer', 'password': 'demo-alfa-2026'})
        assert viewer.get(f'/api/runs/{run_id}').status_code == 404


def test_new_validation_version_invalidates_cache_and_allows_bounded_refresh(client, db):
    parent_id, body = old_checked_run(client, db)
    parent = db.get(Run, parent_id)
    parent.result = {**parent.result, 'search_version': SEARCH_VERSION, 'validation_version': 'old-validation'}
    parent.cache_key = 'prior-prompt-and-validation-version'
    db.commit()
    before = client.get(f'/api/runs/{parent_id}').json()
    assert before['validation_outdated'] and not before['search_outdated']
    response = client.post(f'/api/insights/{parent_id}/refresh')
    assert response.status_code == 202 and response.json()['run_id'] != parent_id
    child = db.get(Run, response.json()['run_id'])
    assert child.parent_id == parent_id and child.trace[0]['step'] == 'Режим пересчёта'
    assert client.get(f'/api/runs/{parent_id}').json()['result'] == before['result']
