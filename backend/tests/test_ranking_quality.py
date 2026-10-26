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
    assert gold['exposure']['level'] == 'unknown'
    assert gold['score'] == 0 and not gold['eligible']


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


def test_stale_topics_and_matching_region_do_not_create_a_business_mechanism():
    company=context('Производство металлопродукции',CL_PRODUCT_LOA_MARK=True,CL_PRODUCT_DEP_MARK=True)
    company['region']='Москва'
    unrelated=event('В Москве прошёл концерт')
    unrelated.topics=['rates','liquidity','commodities']
    for role in ('CEO','CFO','TREASURER'):
        result=rank_event(unrelated,company,role,as_of=NOW)
        assert result['score']==0 and not result['eligible']
        assert not result['feature_keys']


def test_pharma_signal_is_specific_and_role_dependent():
    pharma=context('Торговля оптовая фармацевтической продукцией',CL_PRODUCT_RKO_MARK=True)
    flu=event('Рост заболеваемости гриппом: продолжается вакцинация')
    assert rank_event(flu,pharma,'CEO',as_of=NOW)['score'] > rank_event(flu,pharma,'TREASURER',as_of=NOW)['score']
    assert not rank_event(flu,context('Производство металлоконструкций'),'CEO',as_of=NOW)['eligible']
    pharma['features']['FTS_COUNTRY_NAME']={'value':'ИНДИЯ'}
    assert not rank_event(event('В Индии отбуксировали арестованный нефтяной танкер'),pharma,'CEO',as_of=NOW)['eligible']


def test_retail_indicator_is_background_not_corporate_offer():
    company=context('Производство',CL_PRODUCT_DEP_MARK=True)
    result=rank_event(event('Ставки по вкладам физических лиц остались без изменений'),company,'TREASURER',as_of=NOW)
    assert result['eligible'] and result['score']<40 and result['exposure']['level']=='indirect'
    assert any('не являются корпоративными' in reason for reason in result['reasons'])


def test_steel_verb_and_foreign_fuel_do_not_create_domestic_exposure():
    story=event('Президент Франции договорился о зимних поставках')
    story.focus_text=story.title+'\nГлавным результатом стали договоренности о поставках дизтоплива во Францию.'
    assert not rank_event(story,context('Производство металлоконструкций'),'CEO',as_of=NOW)['eligible']
    assert rank_event(event('Выросли цены на стали различных марок'),context('Производство металлоконструкций'),'CEO',as_of=NOW)['eligible']
    carrier=context('Деятельность автомобильного грузового транспорта')
    assert not rank_event(event('Цены на топливо в ЕС выросли'),carrier,'TREASURER',as_of=NOW)['eligible']


def test_background_rate_and_bank_only_rules_do_not_match_company():
    from app.news_focus import source_focus
    company=context('Производство',CL_PRODUCT_LOA_MARK=True,CL_PRODUCT_DEP_MARK=True)
    bond=event('ЦБ не ждёт волны дефолтов облигаций')
    bond.focus_text=source_focus(bond.title,[{'content':'Обсуждаются дефолты на рынке облигаций.\n\nДля справки: ключевая ставка осталась прежней.'}])
    assert not rank_event(bond,company,'CFO',as_of=NOW)['eligible']
    for title in ['Требования к отчетности кредитных организаций изменились',
                  'Малые банки просят отменить социальные вклады физических лиц']:
        assert not rank_event(event(title),company,'CFO',as_of=NOW)['eligible']
