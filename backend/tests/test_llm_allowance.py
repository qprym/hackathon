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


def test_authorized_extension_preserves_first_twenty_and_stops_at_forty(gateway, db, monkeypatch):
    db.add(LlmAllowance(key=llm.ALLOWANCE_KEY, requests=20, spent=0.1))
    db.commit()
    monkeypatch.setattr(settings(), 'llm_request_limit', 40)
    def attempt(index):
        try:
            llm.complete_json('test', {'i': index}, max_tokens=8)
            return True
        except llm.BudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(30))) == 20
    assert len(gateway) == 20
    db.expire_all()
    assert llm.allowance_status(db)['requests_used'] == 40
    assert llm.allowance_status(db)['requests_remaining'] == 0


def test_new_extension_allows_only_twenty_more_after_thirty_nine(gateway, db, monkeypatch):
    db.add(LlmAllowance(key=llm.ALLOWANCE_KEY, requests=39, spent=0.1))
    db.commit()
    monkeypatch.setattr(settings(), 'llm_request_limit', 59)
    def attempt(index):
        try:
            llm.complete_json('test', {'i': index}, max_tokens=8)
            return True
        except llm.BudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(30))) == 20
    assert len(gateway) == 20
    db.expire_all()
    assert llm.allowance_status(db)['requests_used'] == 59
    assert llm.allowance_status(db)['requests_remaining'] == 0


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


def test_deepseek_flash_disables_default_thinking_and_rejects_another_model(gateway, monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, 'llm_base_url', 'https://api.deepseek.com')
    monkeypatch.setattr(cfg, 'llm_analysis_model', 'DeepSeek-V4.1-Flash')
    monkeypatch.setattr(cfg, 'llm_analysis_id', 'deepseek-flash')
    requests = []
    def respond(url, **kwargs):
        requests.append(kwargs['json'])
        assert url == 'https://api.deepseek.com/chat/completions'
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
            'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]})
    monkeypatch.setattr(llm.httpx, 'post', respond)
    assert llm.complete_json('Return JSON', {}, max_tokens=16) == {'ok': True}
    assert requests[0]['thinking'] == {'type': 'disabled'}
    assert requests[0]['max_tokens'] == 16
    assert llm.complete_json('Return JSON', {}, max_tokens=64, reasoning=True) == {'ok': True}
    assert requests[1]['thinking'] == {'type': 'enabled'}
    assert requests[1]['reasoning_effort'] == 'high'
    assert 'temperature' not in requests[1]
    monkeypatch.setattr(cfg, 'llm_analysis_id', 'deepseek-v4-pro')
    with pytest.raises(llm.ModelUnavailable):
        llm.complete_json('Return JSON', {})
    assert len(requests) == 2


@pytest.mark.parametrize('status', [401, 402, 429])
def test_provider_errors_are_safe_counted_and_not_retried(gateway, monkeypatch, status):
    calls = []
    def respond(url, **kwargs):
        calls.append(url)
        return httpx.Response(status, request=httpx.Request('POST', url),
            json={'error': 'must-not-display-provider-body-or-key'})
    monkeypatch.setattr(llm.httpx, 'post', respond)
    with pytest.raises(llm.ModelUnavailable) as error:
        llm.complete_json('Return JSON', {}, max_tokens=16)
    assert str(status) in str(error.value) and 'must-not-display' not in str(error.value)
    assert len(calls) == 1
    with SessionLocal() as db:
        assert llm.allowance_status(db)['requests_used'] == 1


def test_truncated_json_is_not_accepted_even_when_parseable(gateway, monkeypatch):
    def respond(url, **kwargs):
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
            'choices': [{'finish_reason': 'length', 'message': {'content': '{"ok":true}'}}]})
    monkeypatch.setattr(llm.httpx, 'post', respond)
    with pytest.raises(llm.ModelUnavailable, match='обрезан'):
        llm.complete_json('Return JSON', {}, max_tokens=16)
