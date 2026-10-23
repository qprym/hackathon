import copy
import json

import pytest

from app.review import apply_patch_to_insight, assess_review, review_packet, quote_present
from app.schemas import Claim, Insight
from app.validation import model_grounds, validate_insight, numeric_values
from review_helpers import accepted_review, rejected_review


def sample():
    # Invented values/profile, reproducing the saved failure modes without private documents.
    evidence = [
        {'id': 'doc:0', 'document_id': 'doc', 'kind': 'news', 'published_at': '2026-10-21T00:00:00Z',
         'excerpt': 'Средняя максимальная ставка вкладов физлиц — 12,34%.'},
        {'id': 'doc:1', 'document_id': 'doc', 'kind': 'news', 'published_at': '2026-10-21T00:00:00Z',
         'excerpt': 'Показатель — среднее максимальных ставок десяти банков.'},
        {'id': 'prior:0', 'document_id': 'prior', 'kind': 'news', 'published_at': '2026-10-13T00:00:00Z',
         'excerpt': 'Средняя максимальная ставка вкладов физлиц — 12,20%.'},
    ]
    sources, aliases = model_grounds(evidence)
    context = {'features': {'loan': {'value': True, 'source': 'test.csv row 1'},
                            'lease': {'value': True, 'source': 'test.csv row 1'}},
               'missing': ['Условия договоров неизвестны.'], 'limitations': ['Единицы сумм неизвестны.']}
    insight = Insight(headline='Мониторинг ставок',
        facts=[Claim(text='21 октября 2026 средняя максимальная ставка десяти банков — 12,34%.', evidence_ids=['E1', 'E2'])],
        impact=[Claim(text='У компании есть кредит и лизинг. Если новая котировка выше плана, пересчитать расходы.',
                      feature_keys=['loan', 'lease'], evidence_ids=['E1'], assumption=True)],
        limitations=['Розничная ставка не является корпоративной котировкой.', 'Единицы сумм неизвестны.'])
    return insight, sources, context


def packet_for(insight, sources, context):
    return review_packet(insight, sources, context, event_title='Мониторинг ставок', event_date='2026-10-21')


def test_joint_evidence_and_company_grounding_keep_source_dates():
    insight, sources, context = sample()
    assert not validate_insight(insight, sources, context)
    packet = packet_for(insight, sources, context)
    assert packet['document_groups'] == {'D1': ['E1', 'E2'], 'D2': ['E3']}
    assert packet['company_grounds']['impact.0']['lease']['value'] is True
    assert packet['evidence'][2]['published_at'].startswith('2026-10-13')
    assert packet['company_limitations'] == context['missing'] + context['limitations']
    review = accepted_review(packet)
    # Joint proof: only E1 contains the number, E2 supports the methodology.
    assert assess_review(review, packet)[0] == []
    review['editorial_notes'] = [{'item_id': 'limitations.1', 'suggestion': 'Можно сократить предупреждение.'}]
    assert assess_review(review, packet)[0] == []


def test_quote_whitespace_does_not_change_words_values_or_source_identity():
    assert quote_present('Ставка 12,34%. Условия договора.', 'Ставка\u00a012,34%.\nУсловия  договора.')
    for quote in ('Ставка 12,35%.', 'Ставка 12,34%. ... договора.', 'Условия кредита.', '   '):
        assert not quote_present(quote, 'Ставка\u00a012,34%.\nУсловия  договора.')
    insight, sources, context = sample()
    packet = packet_for(insight, sources, context)
    raw = accepted_review(packet)
    raw['checks'][1]['quotes'][0]['evidence_id'] = 'E3'
    assert assess_review(raw, packet)[0]  # A matching date or similar source is not a substitute.


def test_catalog_preserves_original_text_and_source_bindings():
    insight, sources, context = sample()
    sources[0]['excerpt'] += ('\nТочный\u00a0фрагмент с числом 12,34%. ' * 30) + '\n'
    packet = review_packet(insight, sources, context, event_title=insight.headline,
                           event_date='2026-10-21', quote_catalog=True)
    for original, source in zip(sources, packet['evidence']):
        assert 'excerpt' not in source  # Do not pay to transmit the same text twice.
        assert ''.join(f['text'] for f in source['quote_fragments']) == original['excerpt']
    raw = accepted_review(packet)
    assert not assess_review(raw, packet)[0]
    for ids in ([], ['invented'], ['E3.Q1']):
        broken = copy.deepcopy(raw)
        broken['checks'][1]['quote_ids'] = ids
        issues, targets, _ = assess_review(broken, packet)
        assert issues and not targets
    broken = copy.deepcopy(raw)
    broken['checks'][1]['quotes'] = [{'evidence_id': 'E1', 'quote': sources[0]['excerpt'][:200]}]
    assert assess_review(broken, packet)[0]  # The live protocol never accepts copied substitutes.
    issues, targets, _ = assess_review(rejected_review(packet), packet)
    assert issues and targets == ['impact.0']  # Selecting a quote cannot override a material error.


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(checks=[]),
    lambda r: r['checks'].pop(),
    lambda r: r['checks'].append(copy.deepcopy(r['checks'][0])),
    lambda r: r['checks'][0].update(item_id='unknown'),
    lambda r: r['checks'][0].update(text_span='Такого текста нет'),
    lambda r: r['checks'][1].update(quotes=[]),
    lambda r: r['checks'][1]['quotes'][0].update(quote='Выдуманная цитата'),
    lambda r: r['checks'][2].update(feature_keys=['unavailable']),
    lambda r: r['checks'][0].update(category='temporal'),
    lambda r: r.update(editorial_notes=[{'item_id': 'unknown', 'suggestion': 'Убрать строку'}]),
])
def test_invalid_review_cannot_publish_or_trigger_untrusted_edits(mutation):
    insight, sources, context = sample()
    packet = packet_for(insight, sources, context)
    review = accepted_review(packet)
    mutation(review)
    issues, targets, _ = assess_review(review, packet)
    assert issues and targets == []


def test_material_error_still_blocks_even_with_editorial_notes():
    insight, sources, context = sample()
    packet = packet_for(insight, sources, context)
    raw = rejected_review(packet)
    raw['editorial_notes'] = [{'item_id': 'impact.0', 'suggestion': 'Сократить фразу.'}]
    issues, targets, _ = assess_review(raw, packet)
    assert issues and targets == ['impact.0']
    # Empty legacy verdict is no longer treated as a complete review.
    assert assess_review({'issues': []}, packet)[0]


def test_reviewer_cannot_call_an_attached_feature_missing():
    insight, sources, context = sample()
    packet = packet_for(insight, sources, context)
    raw = rejected_review(packet)
    check = next(c for c in raw['checks'] if c['item_id'] == 'impact.0')
    check['missing_feature_keys'] = ['lease']
    issues, targets, _ = assess_review(raw, packet)
    assert any('уже приложенный' in i for i in issues)
    assert targets == []  # Invalid review is retried, never silently promoted to acceptance.
    del insight.impact[0].feature_keys[1]
    packet = packet_for(insight, sources, context)
    check['feature_keys'] = ['loan']
    issues, targets, _ = assess_review(raw, packet)
    assert issues and targets == ['impact.0']


def test_only_rejected_item_changes_and_complete_result_is_revalidated():
    insight, sources, context = sample()
    before = insight.model_dump()
    changed = Claim(text='Если новая котировка выше плана, проверить графики кредита и лизинга.',
                    feature_keys=['loan', 'lease'], evidence_ids=['E1'], assumption=True)
    result = apply_patch_to_insight(insight, {'edits': [{'item_id': 'impact.0', 'replacement': changed.model_dump()}]}, ['impact.0'])
    assert result.impact == [changed]
    for section in ('facts', 'headline', 'limitations'):
        assert getattr(result, section) == getattr(insight, section)
    assert insight.model_dump() == before
    assert not validate_insight(result, sources, context)


@pytest.mark.parametrize('edits', [
    [{'item_id': 'facts.0', 'replacement': None}],
    [{'item_id': 'impact.0', 'replacement': None}],
    [{'item_id': 'impact.0', 'replacement': 'Неправильный тип'}],
    [{'item_id': 'impact.0', 'replacement': None}, {'item_id': 'impact.0', 'replacement': None}],
    [],
])
def test_patch_cannot_rewrite_unrelated_facts_or_remove_all_impact(edits):
    insight, _, _ = sample()
    with pytest.raises(ValueError):
        apply_patch_to_insight(insight, {'edits': edits}, ['impact.0'])


def test_numeric_dates_ranges_and_negative_values_have_distinct_meanings():
    context = {'features': {}}
    source = {'id': 'source', 'kind': 'bank', 'published_at': '2026-09-11T00:00:00Z',
              'excerpt': 'Ставка 12,34%. Срок от 91 до 180 дней. Динамика −5%.'}
    def check(text):
        insight = Insight(headline='Проверка', bank_view=[Claim(text=text, evidence_ids=['source'])],
                          impact=[Claim(text='При изменении условий проверить договор.', evidence_ids=['source'], assumption=True)])
        return validate_insight(insight, [source], context)
    for text in ('На 11.09.2026 ставка 12,34%.', 'В сентябре 2026 ставка 12,34%.',
                 'В 2026 году ставка 12,34%.', 'Срок 91–180 дней, ставка 12,34%, динамика -5%.'):
        assert not check(text), (text, check(text))
    for text in ('Ставка 11%.', 'Ставка 2026%.', 'На 12.09.2026 ставка 12,34%.',
                 'Срок 91–181 дней.', 'Динамика 5%.', 'В октябре 2026 ставка 12,34%.'):
        assert check(text), text


@pytest.mark.parametrize('short,full', [
    ('40 тыс. т', '40 000 т'), ('40 тысяч тонн', '40000 тонн'),
    ('1,5 млн рублей', '1 500 000 рублей'), ('340 млрд долларов', '340000000000 долларов'),
    ('2 миллиарда', '2000000000'), ('−2,5 млн', '-2500000'), ('0,5 трлн', '500000000000'),
])
def test_explicit_numeric_scales_are_exact(short, full):
    assert numeric_values(short) == numeric_values(full)


def test_number_scale_cannot_justify_a_different_quantity():
    evidence = [{'id':'news', 'kind':'news', 'excerpt':'Танкер перевозит 40 000 т дизеля.'}]
    def check(text):
        return validate_insight(Insight(headline='Перевозка', facts=[Claim(text=text,evidence_ids=['news'])],
            impact=[Claim(text='Если есть закупки топлива, уточнить календарь.',assumption=True)]),
            evidence, {'features':{}}, event_source_ids={'news'})
    assert not check('Танкер перевозит 40 тыс. т дизеля.')
    for text in ('Танкер перевозит 40 т дизеля.', 'Танкер перевозит 41 тыс. т дизеля.',
                 'Танкер перевозит 40 млн т дизеля.'):
        assert check(text)


def test_fact_assumption_and_bank_source_cannot_bypass_event_grounding():
    insight = Insight(headline='Новость', facts=[Claim(text='Ставка 14%.', evidence_ids=['bank'], assumption=True)],
                      impact=[Claim(text='Нужно уточнить условия договора.', assumption=True)])
    evidence = [{'id': 'bank', 'kind': 'bank', 'excerpt': 'Ставка 14%.'}]
    issues = validate_insight(insight, evidence, {'features': {}}, event_source_ids={'news'})
    assert any('меткой предположения' in issue for issue in issues)
    assert any('исходные новости' in issue for issue in issues)


def test_offline_replay_does_not_borrow_missing_packets_or_call_model(tmp_path, monkeypatch):
    from app.replay_reviews import replay
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('Offline replay must not use network'))
    run = {'id': 'saved', 'status': 'failed', 'result': None, 'trace': [
        {'step': 'Черновик анализа', 'details': {'attempt': 0, 'draft': Insight(headline='Событие').model_dump()}},
        {'step': 'Проверка оснований', 'details': {'attempt': 0, 'issues': ['Ошибка источника']}}]}
    path = tmp_path / 'live-test.json'
    path.write_text(json.dumps({'run': run}), encoding='utf-8')
    original = path.read_bytes()
    report = replay(tmp_path)
    assert report['paid_calls'] == 0
    assert report['records'][0]['snapshot'] == 'missing'
    assert report['records'][0]['local_issues_now'] is None
    assert report['records'][0]['semantic_status'] == 'not_rechecked'
    assert path.read_bytes() == original


def test_review_failure_preserves_exact_packet_before_error(client, db, monkeypatch):
    from app import agent
    from app.config import settings
    from app.llm import ModelUnavailable
    from app.worker import process_one
    from test_live_recovery import rejected_run
    parent_id, _ = rejected_run(client, db)
    packets = []
    def fake(system, payload, **kwargs):
        if 'Проверь, подтверждаются' in system:
            packets.append(payload)
            raise ModelUnavailable('Сохранённый сценарий усечённого ответа')
        return {'headline': payload['event'], 'impact': [{'text': 'Если предстоит погашение, проверить договор.',
            'feature_keys': ['CL_PRODUCT_LOA_MARK'], 'assumption': True}]}
    monkeypatch.setattr(settings(), 'demo_mode', False)
    monkeypatch.setattr(agent, 'complete_json', fake)
    run_id = client.post('/api/insights/' + parent_id + '/retry').json()['run_id']
    process_one()
    run = client.get('/api/runs/' + run_id).json()
    assert run['status'] == 'failed'
    saved = next(t['details']['payload'] for t in run['trace'] if t['step'] == 'Пакет проверки')
    assert saved == packets[0]
    assert saved['company_grounds']['impact.0']['CL_PRODUCT_LOA_MARK']['value'] is True


def test_incomplete_review_retries_review_without_rewriting_draft(client, db, monkeypatch):
    from app import agent
    from app.config import settings
    from app.worker import process_one
    from test_live_recovery import rejected_run
    parent_id, _ = rejected_run(client, db)
    calls = []
    def fake(system, payload, **kwargs):
        if 'Проверь, подтверждаются' in system:
            calls.append('review')
            return {} if calls.count('review') == 1 else accepted_review(payload)
        calls.append('draft')
        return {'headline': payload['event'], 'impact': [{'text': 'Если предстоит погашение, проверить договор.',
            'feature_keys': ['CL_PRODUCT_LOA_MARK'], 'assumption': True}]}
    monkeypatch.setattr(settings(), 'demo_mode', False)
    monkeypatch.setattr(agent, 'complete_json', fake)
    run_id = client.post('/api/insights/' + parent_id + '/retry').json()['run_id']
    process_one()
    run = client.get('/api/runs/' + run_id).json()
    assert calls == ['draft', 'review', 'review']
    assert run['result']['verification'] == 'checked'


def test_bank_retrieval_never_mutates_original_event_sources(client, db, monkeypatch):
    from app import agent
    from app.config import settings
    from app.models import Event
    from app.worker import process_one
    from sqlalchemy import select
    event = db.scalar(select(Event).where(Event.title.like('Ставка%')))
    source_evidence = agent.event_evidence(db, event)
    original = copy.deepcopy(source_evidence)
    monkeypatch.setattr(agent, 'event_evidence', lambda *args: source_evidence)
    # The demo path also performs bank retrieval and exposes the former list-alias bug.
    assert settings().demo_mode
    run_id = client.post('/api/analyses', json={'company_id': 'demo-metal', 'event_id': event.id, 'role': 'CFO'}).json()['run_id']
    process_one()
    run = client.get('/api/runs/' + run_id).json()
    assert any(e['kind'] == 'bank' for e in run['result']['evidence'])
    assert source_evidence == original
