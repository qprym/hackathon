from datetime import datetime, timedelta
import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient
from app.bank_relevance import SEARCH_VERSION, subject_match
from app.ingestion import import_document
from app.models import Event, Run
from app.retrieval import search_documents
from app.schemas import Claim, Insight
from app.validation import validate_insight
from app.worker import process_one
from app.main import app

DATE = datetime(2026, 10, 23)
FOCUS = 'Набиуллина оценила возможность экспорта дизеля из России'


def document(db, title, body, **kwargs):
    return import_document(db, title=title, content=body, kind='bank', publisher='Тестовый банк',
                           published_at=kwargs.pop('published_at', DATE - timedelta(days=30)), **kwargs)[0]


@pytest.mark.parametrize('query', [FOCUS, FOCUS + ' Сырьевые рынки Внешняя торговля',
                                   'Ликвидность кредит экспорт логистика', 'золото валютный курс'])
def test_expanded_queries_cannot_drift_from_original_diesel_subject(db, query):
    gold = document(db, 'Обзор рынка золота', 'Золото поддерживает спрос на сырьевые рынки. Экспорт и курс влияют на рынок. Банк оценивает возможность роста спроса на золото в России.')
    fuel = document(db, 'Обзор топлива', 'Экспорт дизельного топлива ограничен. Участники рынка обсуждают объёмы производства дизеля, внутренние поставки, условия продаж и стоимость перевозок для покупателей топлива.')
    macro = document(db, 'Макростатистика', 'Финансовые результаты нефтепереработки ухудшились. Рост затрат в отрасли повышает спрос на кредиты, а планирование производства зависит от графика ремонта заводов и логистики.')
    result = search_documents(db, query, kind='bank', before=DATE, focus=FOCUS)
    assert [e['document_id'] for e in result] == [fuel.id, macro.id]
    assert gold.id not in {e['document_id'] for e in result}
    assert [e['relevance']['level'] for e in result] == ['direct', 'background']


def test_document_title_is_not_a_blacklist_or_a_substitute_for_passage(db):
    mixed = document(db, 'Обзор рынка золота', 'Выпуск дизельного топлива увеличился. Экспорт дизеля вырос, но доступность внутренних поставок зависит от загрузки заводов и графика ремонта мощностей нефтепереработки.')
    misleading = document(db, 'Дизельное топливо', 'Рост золотых резервов поддерживает мировой спрос. Инвесторы покупают золото из-за неопределённости валютного курса и ожидаемого изменения ставок по банковским депозитам.')
    result = search_documents(db, FOCUS, kind='bank', before=DATE)
    assert [e['document_id'] for e in result] == [mixed.id]
    assert misleading.id != mixed.id


def test_common_boilerplate_does_not_link_general_macro_to_diesel(db):
    document(db, 'Альфа-Банк: обзор рынков', 'Глава банка оценила возможность роста экспорта в России. Рынки сохраняют повышенный спрос на кредитные ресурсы, а инфляция оказывает влияние на состояние экономики.')
    assert search_documents(db, FOCUS, kind='bank', before=DATE) == []


def test_incidental_oil_mention_in_gold_payment_mechanism_is_not_fuel_research(db):
    document(db, 'Обзор клиринга', 'Создание золотых резервов поддерживает финансовый цикл сырье–юань–золото. Поставщики могут продавать нефть за юани, а затем купить золото на бирже. Расчёты проводятся через клиринг драгоценных металлов.')
    assert search_documents(db, FOCUS, kind='bank', before=DATE) == []


def test_financial_results_title_does_not_match_interest_rate_monitoring(db):
    document(db, 'Российская сталь: прогноз результатов', 'Финансовые результаты компаний стали более устойчивыми. Отрасль ожидает восстановления производства металлопродукции и спроса со стороны строительных предприятий в течение ближайшего квартала.')
    assert search_documents(db, 'Результаты мониторинга максимальных процентных ставок кредитных организаций', kind='bank', before=DATE) == []


@pytest.mark.parametrize('focus,body,level', [
    ('Экспорт золота', 'Спрос на золото растёт.', 'direct'),
    ('Экспорт золота', 'Экспорт дизеля растёт.', 'irrelevant'),
    ('Экспорт дизеля', 'Выпуск бензина растёт.', 'background'),
    ('Производство стали', 'Поставки нефти растут.', 'irrelevant'),
    ('Производство стали', 'Рынок стали стабилен.', 'direct'),
    ('Экспорт газа', 'Обзор газовой отрасли.', 'direct'),
])
def test_subjects_are_not_one_commodity_bucket(focus, body, level):
    assert subject_match(focus, body)['level'] == level


def test_dates_synthetic_scope_and_ocr_quality_remain_enforced(db):
    body = 'Объёмы производства дизельного топлива достаточны. Экспорт дизеля растёт, однако последствия для покупателей зависят от сроков поставок и условий контрактов на топливо.'
    document(db, 'Дизель в будущем', body, published_at=DATE + timedelta(days=1))
    document(db, 'Учебный дизель', body + ' Учебный пример.', synthetic=True)
    document(db, 'Плохой OCR', body + ' Сканы.', chunks=[{'text':body, 'extraction':'ocr', 'confidence':30}])
    assert search_documents(db, FOCUS, kind='bank', before=DATE) == []


def test_unrelated_bank_limitation_does_not_exempt_missing_application():
    sources = [{'id':'b', 'kind':'bank', 'excerpt':'Банк ожидает рост инфляции.'},
               {'id':'n', 'kind':'news', 'excerpt':'Достаточно дизеля.'}]
    insight = Insight(headline='Дизель', bank_view=[Claim(text='Банк ожидает рост инфляции.', evidence_ids=['b'])],
                      impact=[Claim(text='Если закупаем топливо, уточнить договор.', evidence_ids=['n'], assumption=True)],
                      limitations=['Обзор банка о золоте не применим.'])
    assert any('bank_view.0' in issue for issue in validate_insight(insight, sources, {'features':{}}))


@pytest.mark.parametrize('section', ['impact', 'risks', 'opportunities', 'actions', 'answer'])
def test_background_cannot_support_a_personal_claim_even_alongside_news(section):
    sources = [{'id':'b', 'kind':'bank', 'excerpt':'Нефтепереработка замедлилась.', 'relevance':{'level':'background'}},
               {'id':'n', 'kind':'news', 'excerpt':'Достаточно дизеля.'}]
    insight = Insight(headline='Дизель', impact=[Claim(text='Условный сценарий.', evidence_ids=['n'], assumption=True)])
    setattr(insight, section, [Claim(text='Если закупаем дизель, проверить резерв.', evidence_ids=['b','n'], assumption=True)])
    assert any('фоновая аналитика' in issue for issue in validate_insight(insight, sources, {'features':{}}))
    # Exact historical attribution remains publishable as explicitly separated background.
    insight = Insight(headline='Дизель', bank_view=[Claim(text='Нефтепереработка замедлилась.', evidence_ids=['b'])],
                      impact=[Claim(text='Если закупаем топливо, уточнить договор.', evidence_ids=['n'], assumption=True)])
    assert not validate_insight(insight, sources, {'features':{}})


def test_bank_search_preview_is_read_only_and_requires_run_access(client, db):
    event = db.scalar(select(Event))
    run_id = client.post('/api/analyses', json={'event_id':event.id,'company_id':'demo-metal','role':'CFO'}).json()['run_id']
    process_one()
    old = client.get('/api/runs/'+run_id).json()
    for _ in range(2):
        response = client.get('/api/runs/'+run_id+'/bank-research')
        assert response.status_code == 200
        assert response.json()['search_version'] == SEARCH_VERSION
    assert client.get('/api/runs/'+run_id).json() == old
    assert client.get('/api/admin/metrics').json()['llm_allowance']['requests_used'] == 0
    with TestClient(app, headers={'X-Alfa-Request':'1'}) as other:
        other.post('/api/auth/login',json={'username':'viewer','password':'demo-alfa-2026'})
        assert other.get('/api/runs/'+run_id+'/bank-research').status_code == 404


def test_factual_question_can_quote_background_but_cannot_invent_numbers():
    source = {'id':'b','kind':'bank','excerpt':'Выпуск бензина вырос на 5%.', 'relevance':{'level':'background'}}
    insight = Insight(headline='Вопрос', impact=[Claim(text='Экспозиция не определена.', assumption=True)],
        answer=[Claim(text='Банк сообщал: выпуск бензина вырос на 5%.', evidence_ids=['b'])])
    assert not validate_insight(insight, [source], {'features':{}})
    insight.answer[0].text = 'Банк сообщал: выпуск бензина вырос на 50%.'
    assert any('число отсутствует' in issue for issue in validate_insight(insight, [source], {'features':{}}))
