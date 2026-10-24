import copy
import json

import pytest

from app.forecast import price_forecast_issues
from app.review import apply_patch_to_insight, assess_review, review_packet
from app.schemas import Claim, Insight
from app.validation import validate_insight
from review_helpers import accepted_review, rejected_review


SAVED_ACTION = ('Казначейству: сверить платёжный календарь на ноябрь—декабрь с фактическими счетами за дизель '
    'и с крупнейшими исходящими платежами, проверить резерв ликвидности после обязательств. '
    'Цены на топливо в план не прогнозировать; если календарь и резерв подтвердят свободный остаток '
    '— запросить актуальные корпоративные условия размещения средств.')
CORRECTED_ACTION = SAVED_ACTION.replace('Цены на топливо в план не прогнозировать',
    'Не выводить прогноз цен на топливо только из этой новости; для прогноза нужны дополнительные применимые данные и явные допущения')


@pytest.mark.parametrize('text', [
    SAVED_ACTION,
    'Не прогнозировать цены на дизель.',
    'Нельзя прогнозировать цены.',
    'Не следует строить прогноз цен на топливо.',
    'Цены на топливо не прогнозируйте.',
    'Из этой новости нельзя прогнозировать цены вообще.',
    'Для прогноза по этой новости мало данных. Не прогнозировать цены.',
    'По этой новости известны объёмы; цены не прогнозировать.',
    'По этой новости известны объёмы\nЦены не прогнозировать.',
])
def test_blanket_ban_is_not_justified_by_limited_news(text):
    assert price_forecast_issues(text)


@pytest.mark.parametrize('text', [
    CORRECTED_ACTION,
    'Не прогнозировать цены только из этой новости.',
    'Не следует строить прогноз цен на основании только этой новости.',
    'По этой новости нельзя прогнозировать цены.',
    'Не прогнозировать цены без дополнительных данных.',
    'До получения актуальных котировок не прогнозировать цены.',
    'Данных этой статьи недостаточно для прогноза цен.',
    'Прогноз цен допустим при наличии применимых оснований и явных допущений.',
    'Если применимые котировки подтвердят рост цен, пересчитать сценарий расходов.',
    'Не пишите «цены на топливо в план не прогнозировать»: ограничьте вывод одной новостью.',
    'Не запрещайте прогнозировать цены вообще.',
    'Не прогнозировать объём закупок без договоров.',
    'Не прогнозировать объём закупок, пока не получены цены.',
])
def test_scoped_limit_and_supported_forecast_are_not_blanket_bans(text):
    assert not price_forecast_issues(text)


def sample(text=SAVED_ACTION):
    insight = Insight(headline='Новость о дизеле',
        impact=[Claim(text='Если компания закупает дизель, проверить календарь.', assumption=True)],
        actions=[Claim(text=text, assumption=True)])
    context = {'features': {}}
    packet = review_packet(insight, [], context, event_title=insight.headline,
        event_date='2026-10-23', quote_catalog=True)
    return insight, context, packet


def test_local_check_and_saved_positive_review_require_only_action_correction():
    insight, context, packet = sample()
    original = copy.deepcopy(packet)
    assert all(issue.startswith('actions.0:') for issue in validate_insight(insight, [], context))
    assert list(packet['forecast_scope_findings']) == ['actions.0']
    raw = accepted_review(packet)
    raw['editorial_notes'] = [{'item_id': 'actions.0', 'suggestion': 'Сузить запрет до одной новости.'}]
    issues, targets, _ = assess_review(raw, packet)
    assert issues and targets == ['actions.0']
    assert packet == original
    del packet['forecast_scope_findings']  # Replay legacy packets without today's hints.
    assert assess_review(raw, packet)[1] == ['actions.0']
    assert assess_review({}, packet)[1] == []  # Invalid protocol still needs a review retry.


def test_scoped_correction_preserves_other_claims_and_cash_condition():
    insight, context, _ = sample()
    fixed = apply_patch_to_insight(insight, {'edits': [{'item_id':'actions.0',
        'replacement': Claim(text=CORRECTED_ACTION, assumption=True).model_dump()}]}, ['actions.0'])
    assert fixed.impact == insight.impact
    assert fixed.actions[0].text.split('если календарь')[1] == insight.actions[0].text.split('если календарь')[1]
    assert not validate_insight(fixed, [], context)
    packet = review_packet(fixed, [], context, event_title=fixed.headline, event_date='2026-10-23')
    assert assess_review(accepted_review(packet), packet) == ([], [], [])
    # Passing the scope guard never dismisses a genuine missing-ground verdict.
    assert assess_review(rejected_review(packet, 'actions.0'), packet)[1] == ['actions.0']


def test_limitations_checked_but_source_quotes_are_not_rewritten():
    insight, context, _ = sample(CORRECTED_ACTION)
    insight.limitations = ['Цены на дизель не прогнозировать.']
    assert validate_insight(insight, [], context)[0].startswith('limitations.0:')
    insight.limitations = []
    insight.facts = [Claim(text='Автор сказал: «Цены не прогнозировать».', evidence_ids=['news'])]
    evidence = [{'id':'news', 'kind':'news', 'excerpt':insight.facts[0].text}]
    assert not validate_insight(insight, evidence, context)


def test_saved_review_replay_reports_scope_error_without_editing_snapshot(tmp_path):
    from app.replay_reviews import replay
    insight, _, packet = sample()
    path = tmp_path / 'live-test.json'
    path.write_text(json.dumps({'run': {'id':'saved-scope-error', 'status':'completed', 'trace':[
        {'step':'Черновик анализа', 'details':{'attempt':0, 'draft':insight.model_dump()}},
        {'step':'Пакет проверки', 'details':{'attempt':0, 'payload':packet}},
        {'step':'Ответ проверяющего', 'details':{'attempt':0, 'response':accepted_review(packet)}},
    ]}}), encoding='utf8')
    before = path.read_bytes()
    report = replay(tmp_path)
    assert report['paid_calls'] == 0
    assert report['counts']['forecast_scope_flagged_drafts'] == 1
    assert list(report['records'][0]['forecast_scope_issues_now']) == ['actions.0']
    assert report['records'][0]['saved_review_replay']['correction_targets'] == ['actions.0']
    assert path.read_bytes() == before


def test_blanket_ban_is_corrected_before_review_without_touching_other_sections(client, db, monkeypatch):
    from app import agent
    from app.config import settings
    from app.worker import process_one
    from test_live_recovery import rejected_run
    parent_id, _ = rejected_run(client, db)
    calls = []
    def fake(system, payload, **kwargs):
        if 'Проверь, подтверждаются' in system:
            calls.append('review')
            assert not payload['forecast_scope_findings']
            return accepted_review(payload)
        if 'allowed_edits' in payload:
            calls.append('patch')
            assert payload['allowed_edits'] == ['actions.0']
            return {'edits':[{'item_id':'actions.0', 'replacement':
                Claim(text=CORRECTED_ACTION, assumption=True).model_dump()}]}
        calls.append('synthesis')
        return {**sample()[0].model_dump(), 'headline': payload['event']}
    monkeypatch.setattr(settings(), 'demo_mode', False)
    monkeypatch.setattr(agent, 'complete_json', fake)
    run_id = client.post(f'/api/insights/{parent_id}/retry').json()['run_id']
    process_one()
    run = client.get(f'/api/runs/{run_id}').json()
    assert calls == ['synthesis', 'patch', 'review']
    assert run['result']['verification'] == 'checked'
    assert run['result']['actions'][0]['text'] == CORRECTED_ACTION
    assert run['result']['impact'] == sample()[0].model_dump()['impact']
