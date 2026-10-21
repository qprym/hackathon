from app.config import settings
from app.retrieval import classify
from app.models import Event
from app.worker import process_one
from sqlalchemy import select


def test_topic_boundaries():
    assert classify('Поставка товаров в порт') == ['logistics']
    assert classify('Кредитный портфель и ключевая ставка') == ['rates']
    assert 'logistics' not in classify('Экспорт и импорт товаров')
    assert 'logistics' not in classify('Маршруты трансграничных платежей')


def test_live_agent_contract_and_review_retry(client, db, monkeypatch):
    import app.agent as agent
    calls = []
    reviews = [0]
    def fake_model(system, payload, **kwargs):
        calls.append(system)
        if 'Извлеки темы' in system:
            evidence = payload['evidence'][0]
            return {'topics':['rates'], 'facts':[{'text':evidence['excerpt'], 'evidence_id':evidence['id']}]}
        if 'Составь план' in system:
            return {'tools':['event_sources','bank_search','verify','shell'], 'queries':['ставка кредит'], 'objective':'Проверить финансирование'}
        if 'Упорядочь' in system:
            return {'ordered_ids':[e['id'] for e in payload['candidates']]}
        if 'Проверь, подтверждаются' in system:
            reviews[0] += 1
            return {'issues':['Уточнить сценарий'] if reviews[0] == 1 else [], 'search_queries':['кредит ставка']}
        assert 'output_schema' in payload
        evidence = next(e for e in payload['evidence'] if e['kind']=='news')
        return {'headline':payload['event'], 'facts':[{'text':evidence['excerpt'],'evidence_ids':[evidence['id']]}],
            'impact':[{'text':'Если предстоит рефинансирование, проверьте условия кредитов.', 'evidence_ids':[evidence['id']], 'feature_keys':['CL_PRODUCT_LOA_MARK'], 'assumption':True}],
            'answer':[{'text':'Нужны условия договоров.', 'assumption':True}] if payload.get('question') else []}
    monkeypatch.setattr(settings(),'demo_mode',False)
    monkeypatch.setattr(agent,'complete_json',fake_model)
    event = db.scalar(select(Event).where(Event.title.like('Ставка%')))
    run_id = client.post('/api/analyses', json={'company_id':'demo-metal','event_id':event.id,'role':'CFO'}).json()['run_id']
    assert process_one()
    run = client.get('/api/runs/'+run_id).json()
    assert run['status']=='completed' and run['result']['mode']=='live'
    assert reviews[0]==2
    assert any(t['step']=='Дополнительный поиск' for t in run['trace'])
    plan = next(t for t in run['trace'] if t['step']=='План анализа')
    assert 'shell' not in plan['details']['tools']
    assert run['result']['verification']=='checked'


def test_failed_live_verification_hides_personal_interpretation(client, db, monkeypatch):
    import app.agent as agent
    def fake_model(system,payload,**kwargs):
        if 'Извлеки темы' in system:
            return {'topics':['rates'],'facts':[]}
        if 'Составь план' in system:
            return {'tools':[], 'queries':['кредит']}
        if 'Упорядочь' in system:
            return {'ordered_ids':[]}
        if 'Проверь, подтверждаются' in system:
            return {'issues':['Недоказанное утверждение'],'search_queries':[]}
        return {'headline':'Ошибка модели','impact':[{'text':'Гарантированная экономия 100 миллионов.', 'evidence_ids':['invented']}]}
    monkeypatch.setattr(settings(),'demo_mode',False)
    monkeypatch.setattr(agent,'complete_json',fake_model)
    event = db.scalar(select(Event).where(Event.title.like('Ставка%')))
    run_id = client.post('/api/analyses',json={'company_id':'demo-metal','event_id':event.id,'role':'CFO'}).json()['run_id']
    process_one()
    result = client.get('/api/runs/'+run_id).json()['result']
    assert result['verification']=='insufficient'
    assert not result['impact']
    assert '100 миллионов' not in str(result)
