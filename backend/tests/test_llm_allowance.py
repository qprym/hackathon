from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app import llm
from app.config import settings
from app.db import SessionLocal, engine
from app.models import LlmAllowance, Usage


@pytest.fixture
def gateway(monkeypatch):
    cfg = settings()
    values = dict(demo_mode=False, llm_base_url='https://provider.example/v1',
        llm_api_key='local-test-placeholder', llm_analysis_id='approved-analysis',
        llm_extraction_id='approved-extraction', llm_input_rub_per_million=1,
        llm_output_rub_per_million=1, llm_daily_limit_rub=100,
        llm_test_limit_rub=1, llm_request_limit=20)
    for name, value in values.items():
        monkeypatch.setattr(cfg, name, value)
    calls = []
    def respond(url, **kwargs):
        calls.append(kwargs['json']['model'])
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
            'choices': [{'message': {'content': '{"ok": true}'}}]})
    monkeypatch.setattr(llm.httpx, 'post', respond)
    return calls


def test_shared_cap_stops_twenty_first_call_under_concurrency(gateway):
    def attempt(index):
        try:
            llm.complete_json('test', {'i': index}, extraction=index % 2 == 0, max_tokens=8)
            return True
        except llm.BudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(35))) == 20
    assert len(gateway) == 20
    assert set(gateway) == {'approved-analysis', 'approved-extraction'}
    with SessionLocal() as db:
        assert db.get(LlmAllowance, llm.ALLOWANCE_KEY).requests == 20
        assert db.scalar(select(func.count()).select_from(Usage)) == 20


@pytest.mark.parametrize('failure', ['timeout', 'invalid_json'])
def test_failed_calls_consume_slots_without_automatic_retry(gateway, monkeypatch, failure):
    calls = []
    monkeypatch.setattr(settings(), 'llm_request_limit', 2)
    def fail(url, **kwargs):
        calls.append(url)
        if failure == 'timeout':
            raise httpx.ReadTimeout('test timeout')
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'message': {'content': 'not json'}}]})
    monkeypatch.setattr(llm.httpx, 'post', fail)
    for _ in range(2):
        with pytest.raises(llm.ModelUnavailable):
            llm.complete_json('test', {}, max_tokens=8)
    with pytest.raises(llm.BudgetExceeded):
        llm.complete_json('test', {}, max_tokens=8)
    assert len(calls) == 2
    with SessionLocal() as db:
        allowance = llm.allowance_status(db)
        assert allowance['requests_used'] == 2 and allowance['spent_rub'] > 0


def test_cap_persists_across_new_day_and_connection_restart(gateway, monkeypatch):
    monkeypatch.setattr(settings(), 'llm_request_limit', 1)
    llm.complete_json('test', {}, max_tokens=8)
    engine.dispose()
    class Tomorrow:
        @staticmethod
        def now(tz):
            return datetime.now(tz) + timedelta(days=1)
    monkeypatch.setattr(llm, 'datetime', Tomorrow)
    with pytest.raises(llm.BudgetExceeded):
        llm.complete_json('test', {}, max_tokens=8)
    assert len(gateway) == 1


def test_money_limit_blocks_before_http_and_failed_daily_reservation_rolls_back(gateway, monkeypatch):
    monkeypatch.setattr(settings(), 'llm_test_limit_rub', 0)
    with pytest.raises(llm.BudgetExceeded):
        llm.complete_json('test', {}, max_tokens=8)
    monkeypatch.setattr(settings(), 'llm_test_limit_rub', 0.00001)
    with pytest.raises(llm.BudgetExceeded):
        llm.complete_json('test', {}, max_tokens=8)
    monkeypatch.setattr(settings(), 'llm_test_limit_rub', 1)
    monkeypatch.setattr(settings(), 'llm_daily_limit_rub', 0)
    with pytest.raises(llm.BudgetExceeded):
        llm.complete_json('test', {}, max_tokens=8)
    with SessionLocal() as db:
        assert llm.allowance_status(db)['requests_used'] == 0
    assert not gateway


def test_usage_reconciles_money_but_never_refunds_request(gateway, db):
    llm.complete_json('test', {}, max_tokens=8)
    allowance = db.get(LlmAllowance, llm.ALLOWANCE_KEY)
    assert allowance.requests == 1
    assert allowance.spent == pytest.approx(15 / 1_000_000)


def test_admin_can_read_remaining_trial_allowance(client):
    result = client.get('/api/admin/metrics').json()['llm_allowance']
    assert result['request_limit'] == 20 and result['requests_used'] == 0
    assert result['requests_remaining'] == 20
