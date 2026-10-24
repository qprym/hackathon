from datetime import datetime, timedelta
from types import SimpleNamespace
from app.retrieval import classify, rank_event
from app.quality import mode_metrics

NOW = datetime(2026, 10, 24)


def context(industry, **features):
    return {'industry': industry, 'region': '', 'features': {k: {'value': v} for k, v in features.items()}}


def event(title, documents=None):
    return SimpleNamespace(title=title, topics=classify(title), published_at=NOW, document_ids=documents or ['a'])


def test_fts_does_not_make_unrelated_commodity_a_direct_exposure():
    steel = context('Производство строительных металлических конструкций', FTS_FLAG=True)
    gold = rank_event(event('Экспорт золота растёт'), steel, 'CFO', as_of=NOW)
    assert gold['exposure']['level'] == 'indirect'
    assert gold['score'] < 40
    assert 'валюты' in gold['reasons'][0]


def test_diesel_prioritizes_carrier_without_inventing_a_fuel_contract():
    diesel = event('Экспорт дизеля и поставки топлива')
    carrier = rank_event(diesel, context('Деятельность автомобильного грузового транспорта'), 'TREASURER', as_of=NOW)
    manufacturer = rank_event(diesel, context('Производство металлоконструкций', FTS_FLAG=True), 'TREASURER', as_of=NOW)
    assert carrier['score'] > manufacturer['score']
    assert carrier['exposure']['level'] == 'indirect'
    assert any('договоры' in reason for reason in carrier['reasons'])
    assert carrier['score'] < 40


def test_multiple_copies_do_not_raise_relevance_and_clock_is_frozen():
    company = context('Производство металлоконструкций')
    a = rank_event(event('Цены на сталь'), company, 'CEO', as_of=NOW)
    b = rank_event(event('Цены на сталь', ['a', 'a-copy', 'rss']), company, 'CEO', as_of=NOW)
    assert a == b
    assert a['exposure']['level'] == 'direct'
    assert rank_event(event('Цены на сталь'), company, 'CEO', as_of=NOW+timedelta(days=3))['score'] < a['score']


def test_metrics_do_not_mix_demo_latency_or_hide_paid_failures():
    def run(key, mode, seconds, status='completed'):
        return SimpleNamespace(id=key, result={'mode':mode,'verification':'checked'} if mode else None,
            status=status, created_at=NOW, finished_at=NOW+timedelta(seconds=seconds))
    values = mode_metrics([run('demo','demo',1),run('real','live',100),run('failed',None,400,'failed'),run('unknown',None,500)],
        [SimpleNamespace(run_id='real',cost_rub=.4),SimpleNamespace(run_id='failed',cost_rub=.7)])
    assert values['live']['latency_avg_seconds'] == 100
    assert values['live']['statuses']['failed'] == 1
    assert values['live']['provider_cost_rub'] == 1.1
    assert values['demo']['latency_avg_seconds'] == 1
    assert values['unknown']['total'] == 1
    assert values['live']['latency_samples'] == 1
