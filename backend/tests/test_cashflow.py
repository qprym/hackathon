import copy
import pytest
from app.cashflow import cashflow_issues
from app.review import assess_review, review_packet
from app.schemas import Claim, Insight
from app.validation import validate_insight
from review_helpers import accepted_review


SAVED_FAILURE = ('Если достаточный выпуск и возобновление экспорта удержат цены на дизель вблизи плановых, '
    'топливные платежи останутся в бюджете, а высвободившийся остаток можно рассмотреть к размещению '
    '— с запросом актуальной корпоративной котировки (отметки о депозитном продукте в наборе нет).')


@pytest.mark.parametrize('text', [
    SAVED_FAILURE,
    'Если платежи останутся в бюджете, свободные деньги можно разместить.',
    'Расходы не превысят план, поэтому появится экономия.',
    'Затраты в рамках утвержденного бюджета. Высвободившиеся средства разместить.',
    'Бюджет соблюден, значит средства высвободятся для депозита.',
    'Если расходы на уровне плана, появится свободная ликвидность.',
    'Отсутствие перерасхода не гарантирует экономию. Платежи останутся в бюджете, а свободный остаток разместить.',
    'Платежи останутся в бюджете. Если это сохранится, появится свободный остаток.',
    'Платежи останутся в бюджете и не создадут экономию, но высвободившиеся средства можно разместить.',
    'Если расходы ниже плана, экономия образует свободный остаток для депозита.',
    'Подтверждена экономия расходов. Высвободившиеся деньги можно разместить.',
    'Свободный остаток появится, потому что расходы не превысят бюджет.',
    'Экономия возникнет благодаря соблюдению бюджета.',
    'Свободные средства доступны за счёт экономии расходов.',
])
def test_budget_or_savings_cannot_create_cash_by_themselves(text):
    assert cashflow_issues(text), text


@pytest.mark.parametrize('text', [
    'Если платежи останутся в бюджете, дополнительного перерасхода не будет.',
    'Бюджет соблюден, но это не означает экономию или свободный остаток.',
    'Не считайте соблюдение бюджета экономией или свободными средствами.',
    'Нельзя выводить из соблюдения бюджета свободный остаток.',
    'Платежи в пределах бюджета. Свободный остаток не гарантирован.',
    'Расходы в пределах плана: это не доказывает наличие свободных средств.',
    'Бюджет соблюден. Проверьте наличие свободного остатка после обязательств.',
    'Бюджет соблюден. Проверьте, есть ли свободный остаток после обязательств.',
    'Если расходы ниже плана при неизменном объёме закупки, оценить экономию платежей.',
    'Подтверждена экономия расходов, но она не доказывает свободный остаток.',
    'Платежи останутся в бюджете; при подтверждённом свободном остатке запросить условия размещения.',
    'Платежи останутся в бюджете. Если платёжный календарь после обязательств и резерва подтвердит свободный остаток, запросить котировку.',
    'Бюджет соблюден, и есть подтверждённый свободный остаток после обязательств. Можно сравнить условия размещения.',
    'Бюджет соблюден. Платёжный календарь после обязательств подтверждает свободный остаток.',
    'Бюджет соблюден. Свободный остаток подтверждён расчётом после обязательств и резерва.',
    'Свободный остаток не следует из соблюдения бюджета.',
    'Бюджет соблюден. Если высвободятся денежные средства после обязательств, проверить условия размещения.',
    'Подтверждена экономия, при наличии свободного остатка после обязательств можно сравнить котировки.',
    'Сверить платежи с планом; при устойчивом свободном остатке запросить корпоративные условия размещения.',
    'При подтверждённом свободном остатке запросить корпоративные условия его размещения.',
    'Ставка изменилась. При наличии депозитов и свободной ликвидности запросить актуальную котировку.',
    'Бюджет соблюден. Высвободившуюся производственную мощность проверить отдельно.',
])
def test_valid_independent_conditions_and_denials_are_not_blocked(text):
    assert cashflow_issues(text) == [], (text, cashflow_issues(text))


def packet(text=SAVED_FAILURE):
    insight = Insight(headline='Выпуск топлива',
        impact=[Claim(text='Если компания закупает дизель, сверить платёжный календарь.', assumption=True)],
        opportunities=[Claim(text=text, feature_keys=['industry', 'deposit'], assumption=True)],
        limitations=['Свободный остаток не подтверждён.'])
    context = {'features': {'industry': {'value': 'Перевозки', 'source': 'fixture'},
                            'deposit': {'value': False, 'source': 'fixture'}}}
    p = review_packet(insight, [], context, event_title=insight.headline, event_date='2026-10-23', quote_catalog=True)
    return insight, context, p


def test_supported_review_and_attached_features_cannot_override_causality():
    insight, context, p = packet()
    original = copy.deepcopy(p)
    issues = validate_insight(insight, [], context)
    assert issues and all(i.startswith('opportunities.0:') for i in issues)
    raw = accepted_review(p)
    raw['editorial_notes'] = [{'item_id': 'opportunities.0', 'suggestion': 'Уточнить свободный остаток.'}]
    issues, targets, _ = assess_review(raw, p)
    assert issues and targets == ['opportunities.0']
    assert p == original and raw['checks'][2]['verdict'] == 'supported'
    # Also evaluate legacy saved packets without the new hints.
    del p['financial_logic_findings']
    assert assess_review(raw, p)[1] == ['opportunities.0']


def test_independent_cash_condition_is_not_a_schema_or_semantic_error():
    insight, context, p = packet('Сверить расходы с бюджетом. Если календарь после обязательств и резерва подтвердит свободный остаток, запросить условия размещения.')
    assert not validate_insight(insight, [], context)
    assert assess_review(accepted_review(p), p) == ([], [], [])


def test_invalid_review_still_requires_protocol_retry():
    _, _, p = packet()
    issues, targets, _ = assess_review({}, p)
    assert issues and targets == []


def test_known_financial_error_is_corrected_before_spending_on_review(client, db, monkeypatch):
    from app import agent
    from app.config import settings
    from app.worker import process_one
    from test_live_recovery import rejected_run
    parent_id, _ = rejected_run(client, db)
    calls = []
    def fake(system, payload, **kwargs):
        if 'Проверь, подтверждаются' in system:
            calls.append('review')
            assert not payload['financial_logic_findings']
            return accepted_review(payload)
        if 'allowed_edits' in payload:
            calls.append('patch')
            assert payload['allowed_edits'] == ['opportunities.0']
            assert any('Соблюдение бюджета' in issue for issue in payload['corrections'])
            return {'edits': [{'item_id': 'opportunities.0', 'replacement': None}]}
        calls.append('synthesis')
        return {'headline': payload['event'],
            'impact': [{'text': 'Если предстоит погашение кредита, проверить календарь.',
                        'feature_keys': ['CL_PRODUCT_LOA_MARK'], 'assumption': True}],
            'opportunities': [{'text': SAVED_FAILURE, 'assumption': True}]}
    monkeypatch.setattr(settings(), 'demo_mode', False)
    monkeypatch.setattr(agent, 'complete_json', fake)
    run_id = client.post(f'/api/insights/{parent_id}/retry').json()['run_id']
    process_one()
    run = client.get(f'/api/runs/{run_id}').json()
    assert calls == ['synthesis', 'patch', 'review']
    assert run['result']['verification'] == 'checked' and not run['validation_outdated']
    assert run['result']['opportunities'] == []
    assert run['result']['impact'][0]['text'] == 'Если предстоит погашение кредита, проверить календарь.'


def test_saved_positive_verdict_replay_is_read_only_and_offline(tmp_path, monkeypatch):
    import json
    import socket
    from app.replay_reviews import replay
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('Offline replay attempted network'))
    insight, _, p = packet()
    raw = accepted_review(p)
    record = {'run': {'id': 'saved-financial-error', 'status': 'completed', 'trace': [
        {'step': 'Черновик анализа', 'details': {'attempt': 0, 'draft': insight.model_dump()}},
        {'step': 'Пакет проверки', 'details': {'attempt': 0, 'payload': p}},
        {'step': 'Ответ проверяющего', 'details': {'attempt': 0, 'response': raw}},
        {'step': 'Проверка оснований', 'details': {'attempt': 0, 'passed': True, 'issues': []}},
    ]}}
    path = tmp_path / 'live-saved.json'
    path.write_text(json.dumps(record), encoding='utf-8')
    before = path.read_bytes()
    report = replay(tmp_path)
    result = report['records'][0]
    assert report['paid_calls'] == 0 and result['snapshot'] == 'missing'
    assert result['saved_review_replay']['correction_targets'] == ['opportunities.0']
    assert list(result['cashflow_issues_now']) == ['opportunities.0']
    assert path.read_bytes() == before
