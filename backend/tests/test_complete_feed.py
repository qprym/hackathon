from copy import deepcopy
from datetime import timedelta
import pytest
from sqlalchemy import select, update
from app import full_selection as full, semantic_ranking as sr
from app.config import settings
from app.db import SessionLocal, utcnow
from app.models import User, Company, RankingJob, Run, Link, RelevanceAssessment
from app.leases import owned, renew, deadline, LeaseLost
from test_semantic_ranking import real_article, output


def response(packet,decision='scenario'):
    if 'review_schema' in packet:
        return {'approved':True,'reason':'Все статьи, основания и порядок проверены.','replacement':None}
    if packet['output_schema'].get('title')=='EventMatch':
        return {'same_event':False,'reason':'Похожие заголовки описывают разные события.',
            'grounds':[{'article_id':a['article_id'],'source_id':a['documents'][0]['source_id'],
                       'quote':a['documents'][0]['text'][-100:]} for a in packet['articles']]}
    if packet['output_schema'].get('title')=='Comparison':
        return {'first':packet['articles'][0]['article_id'],'same_event':False,'reason':'Первый материал даёт более конкретный сигнал для роли.',
            'grounds':[{'article_id':a['article_id'],'feature_key':'MAINOKVED_NAME','source_id':a['documents'][0]['source_id'],
                       'quote':a['documents'][0]['text'][-100:]} for a in packet['articles']]}
    rows=[]
    for a in packet['articles']:
        grade={'decision':decision,'reason':'Отраслевой сигнал полезен для проверки закупочных условий; договоры неизвестны.',
               'feature_key':'MAINOKVED_NAME','source_id':a['documents'][0]['source_id'],'quote':a['documents'][0]['text'][-100:]}
        rows.append({'article_id':a['article_id'],**{r:dict(grade) for r in sr.ROLES},'duplicate_of':None,'duplicate_reason':None})
    return {'decisions':rows,'order':{r:[a['article_id'] for a in packet['articles']] if decision in ('scenario','direct') else [] for r in sr.ROLES}}


def setup(db,monkeypatch,count=7):
    monkeypatch.setattr(settings(),'demo_mode',False)
    user=db.scalar(select(User).where(User.username=='demo'));company=db.get(Company,'demo-metal')
    events=[]
    for i in range(count):
        _,e=real_article(db,title=f'Отраслевой выпуск {i}',text=f'Уникальное событие {i}. '+('Подтверждённый контекст производства. '*5))
        events.append(e)
    return user,company,events


def test_complete_feed_recovers_zeros_and_paginates_without_calls(client,db,monkeypatch):
    user,company,events=setup(db,monkeypatch)
    monkeypatch.setattr(sr,'complete_json',lambda policy,packet,**kw:output(packet,0))
    for job in sr.enqueue(db,user,company,events)['job_ids']:sr.process_one(job)
    assert client.get('/api/feed',params={'company_id':company.id}).json()['items']==[]
    seen=[]
    def fake(policy,packet,**kw):seen.append(deepcopy(packet));return response(packet)
    monkeypatch.setattr(full,'complete_json',fake)
    queued=full.enqueue(db,user,company);sr.process_one(queued['job_id']);db.expire_all()
    job=db.get(RankingJob,queued['job_id']);assert job.status=='completed',job.error
    assert len(seen)==2 and len(seen[0]['articles'])==7
    first=client.get('/api/feed',params={'company_id':company.id,'limit':5}).json()
    assert first['total']==7 and len(first['items'])==5 and first['next_offset']==5
    assert first['ordering_version']==full.VERSION and first['items'][0]['applicability']=='scenario'
    real_article(db,'Позднее событие не меняет уже открытые страницы')
    second=client.get('/api/feed',params={'company_id':company.id,'limit':5,'offset':5,'feed_version':first['feed_version']}).json()
    assert len(second['items'])==2 and second['next_offset'] is None
    assert not {i['id'] for i in first['items']}&{i['id'] for i in second['items']}
    assert len(seen)==2
    assert client.get('/api/feed',params={'company_id':company.id,'role':'CEO','feed_version':first['feed_version']}).status_code==409
    company.name+=' новое';db.commit()
    assert client.get('/api/feed',params={'company_id':company.id,'feed_version':first['feed_version']}).status_code==409


@pytest.mark.parametrize('error',['omission','order','quote','feature','cycle','unknown','review'])
def test_full_selection_strict_contract(client,db,monkeypatch,error):
    user,company,_=setup(db,monkeypatch,2);packet=full.from_database(db,user,company);raw=response(packet)
    if error=='omission':raw['decisions'].pop()
    if error=='order':raw['order']['CFO'].pop()
    if error=='quote':raw['decisions'][0]['CEO']['quote']='Выдуманная цитата о прибыли'
    if error=='feature':raw['decisions'][0]['CEO']['feature_key']='fake'
    if error=='unknown':raw['decisions'][0]['article_id']='unknown'
    if error=='cycle':
        raw['decisions'][0].update(duplicate_of=raw['decisions'][1]['article_id'],duplicate_reason='Та же публикация')
        raw['decisions'][1].update(duplicate_of=raw['decisions'][0]['article_id'],duplicate_reason='Та же публикация')
    if error!='review':
        with pytest.raises(ValueError):full.validate(raw,packet)
    else:
        def fake(policy,packet,**kw):
            out=response(packet)
            if 'review_schema' in packet:out['replacement']=raw
            return out
        monkeypatch.setattr(full,'complete_json',fake)
        q=full.enqueue(db,user,company);sr.process_one(q['job_id']);db.expire_all()
        assert db.get(RankingJob,q['job_id']).status=='failed'
        assert client.get('/api/feed',params={'company_id':company.id}).json()['items']==[]


def test_all_excluded_stays_empty_with_old_positive_scores(client,db,monkeypatch):
    user,company,events=setup(db,monkeypatch,1)
    monkeypatch.setattr(sr,'complete_json',lambda policy,payload,**kw:output(payload,2))
    sr.process_one(sr.enqueue(db,user,company,events)['job_ids'][0])
    monkeypatch.setattr(full,'complete_json',lambda policy,packet,**kw:response(packet,'irrelevant'))
    q=full.enqueue(db,user,company);sr.process_one(q['job_id']);db.expire_all()
    assert db.get(RankingJob,q['job_id']).status=='completed'
    assert not client.get('/api/feed',params={'company_id':company.id}).json()['items']
    assert client.get('/api/feed',params={'company_id':company.id,'scope':'all'}).json()['total']==1


def test_full_text_envelope_never_slices_and_merge_is_model_reviewed(client,db,monkeypatch):
    user,company,_=setup(db,monkeypatch,14)
    packet=full.from_database(db,user,company)
    chunks=list(full.packets(packet));assert len(chunks)>1
    assert sorted((a for p in chunks for a in p['articles']),key=lambda a:a['article_id'])==sorted(packet['articles'],key=lambda a:a['article_id'])
    seen=[]
    monkeypatch.setattr(full,'complete_json',lambda policy,p,**kw:(seen.append(p),response(p))[1])
    q=full.enqueue(db,user,company);sr.process_one(q['job_id']);db.expire_all()
    job=db.get(RankingJob,q['job_id']);assert job.status=='completed',job.error
    assert any(p.get('role')=='CFO' for p in seen)
    assert len(job.response['order']['CFO'])==14
    assert all(s['response'] for s in job.response['steps'])
    packet['articles'][0]['documents'][0]['text']='Последний абзац. '*50000
    with pytest.raises(Exception,match='не помещается'):list(full.packets(packet))


def test_filters_keep_model_order_and_search_full_body(client,db,monkeypatch):
    user,company,_=setup(db,monkeypatch,3)
    def fake(policy,p,**kw):
        out=response(p)
        if 'order' in out:
            for r in sr.ROLES:out['order'][r].reverse()
        return out
    monkeypatch.setattr(full,'complete_json',fake)
    q=full.enqueue(db,user,company);sr.process_one(q['job_id'])
    params={'company_id':company.id}
    base=client.get('/api/feed',params=params).json()['items']
    found=client.get('/api/feed',params={**params,'q':'Подтверждённый контекст','scope':'personal'}).json()['items']
    assert [e['id'] for e in found]==[e['id'] for e in base]


def test_local_scheduler_idempotent_and_remote_cannot_spend(client,db,monkeypatch):
    from app.pipeline import schedule
    user,company,events=setup(db,monkeypatch,2)
    viewer=db.scalar(select(User).where(User.username=='viewer'));viewer.company_ids=[];db.commit()
    for key,val in {'auto_personalization':True,'neural_ranking_worker':True,'llm_base_url':'http://localhost:8001/v1',
                    'active_company_ids':company.id}.items():monkeypatch.setattr(settings(),key,val)
    assert schedule()==[]
    assert not db.scalars(select(RankingJob)).all()
    monkeypatch.setattr(settings(),'llm_provider_mode','local')
    monkeypatch.setattr(sr,'complete_json',lambda policy,p,**kw:output(p,0))
    monkeypatch.setattr(full,'complete_json',lambda policy,p,**kw:response(p))
    schedule();schedule();db.expire_all()
    assert len(db.scalars(select(RankingJob)).all())==1
    assert sr.process_one()
    schedule();schedule();assert sr.process_one()
    db.expire_all();completed=db.scalar(select(RankingJob).where(RankingJob.payload['purpose'].as_string()=='full_feed'))
    assert completed.status=='completed',completed.error
    count=len(db.scalars(select(RankingJob)).all());schedule()
    assert len(db.scalars(select(RankingJob)).all())==count


def test_heartbeat_and_fencing_reject_late_worker(client,db,monkeypatch):
    user,company,_=setup(db,monkeypatch,1)
    job=RankingJob(user_id=user.id,company_id=company.id,payload={},cache_keys=[],status='running',lease_token='old',lease_until=deadline())
    db.add(job);db.commit();key=job.id
    assert renew(RankingJob,key,'old')
    assert not renew(RankingJob,key,'other')
    with owned(RankingJob,key,'old'):
        with SessionLocal() as other:
            other.execute(update(RankingJob).where(RankingJob.id==key).values(lease_token='replacement'));other.commit()
        job.status='completed'
        with pytest.raises(LeaseLost):db.commit()
        db.rollback()
    db.expire_all();assert db.get(RankingJob,key).status=='running'


def test_relationship_search_reaches_beyond_ten_and_keeps_permissions(client,db):
    company=db.get(Company,'demo-metal');user=db.scalar(select(User).where(User.username=='demo'))
    for i in range(15):
        c=Company(id=f'new-{i}',name=f'Контрагент {i}',industry='Фармацевтика' if i==14 else 'Металлургия',region='Регион',synthetic=True)
        db.add(c);db.add(Link(id=f'l-{i}',kind='payment',source_id=company.id,target_id=c.id,amount=100-i))
    user.company_ids=[*user.company_ids,'new-14'];db.commit()
    result=client.get(f'/api/companies/{company.id}/relations',params={'q':'Фармацевтика'}).json()
    assert result['items'][0]['id']=='new-14'
    result=client.get(f'/api/companies/{company.id}/relations',params={'q':'Металлургия'}).json()
    assert all(not e['id'].startswith('new-') for e in result['items'])


@pytest.mark.parametrize('same',[True,False])
def test_title_similarity_needs_review_and_all_confirmed_sources_reach_analysis(client,db,monkeypatch,same):
    user,company,events=setup(db,monkeypatch,2)
    original=full.packets
    monkeypatch.setattr(full,'packets',lambda p:({**p,'articles':[a]} for batch in original(p) for a in batch['articles']))
    def fake(policy,p,**kw):
        result=response(p)
        if p['output_schema'].get('title')=='EventMatch' and 'review_schema' not in p:result['same_event']=same
        return result
    monkeypatch.setattr(full,'complete_json',fake)
    queued=full.enqueue(db,user,company);assert sr.process_one(queued['job_id'])
    db.expire_all();job=db.get(RankingJob,queued['job_id']);assert job.status=='completed',job.error
    page=client.get('/api/feed',params={'company_id':company.id}).json()
    assert page['total']==(1 if same else 2)
    assert len(full.verified_source_ids(db,user,company,events[0]))==(2 if same else 1)
    if same:assert len(page['items'][0]['related_publications'])==1


def test_old_analysis_failure_cannot_overwrite_replacement(client,db,monkeypatch):
    from app import worker
    from app.models import Event,Audit
    event=db.scalar(select(Event).where(Event.synthetic.is_(True)))
    run_id=client.post('/api/analyses',json={'company_id':'demo-metal','role':'CFO','event_id':event.id}).json()['run_id']
    def failed(session,run):
        with SessionLocal() as replacement:
            replacement.execute(update(Run).where(Run.id==run.id).values(lease_token='new-owner'));replacement.commit()
        raise ValueError('Late provider failure')
    monkeypatch.setattr(worker,'run_agent',failed)
    assert worker.process_one()
    db.expire_all();run=db.get(Run,run_id)
    assert run.status=='running' and run.lease_token=='new-owner' and run.error is None
    assert not db.scalars(select(Audit).where(Audit.action=='run_failed')).all()


def test_news_arrival_during_long_selection_keeps_reviewed_snapshot_visible(client,db,monkeypatch):
    user,company,_=setup(db,monkeypatch,2)
    added=False
    def fake(policy,p,**kw):
        nonlocal added
        if not added:
            added=True
            real_article(db,title='Новый отдельный выпуск',text='Новая статья поступила во время обработки, не изменяя уже проверенные источники. Доступность результата не должна зависеть от паузы в новостном потоке.')
        return response(p)
    monkeypatch.setattr(full,'complete_json',fake)
    q=full.enqueue(db,user,company);sr.process_one(q['job_id']);db.expire_all()
    job=db.get(RankingJob,q['job_id']);assert job.status=='completed',job.error
    feed=client.get('/api/feed',params={'company_id':company.id}).json()
    assert feed['total']==2
    assert job.response['new_articles_pending']==1
    next_job=full.enqueue(db,user,company);assert next_job['job_id']!=job.id
    company.industry='Другой контекст';db.commit()
    assert not full.compatible_snapshot(job.payload,full.from_database(db,user,company))


def test_legacy_pdf_pages_show_unknown_visuals_and_empty_page(client,db):
    from app.ingestion import import_document
    doc,_=import_document(db,title='Страницы старого импорта',kind='bank',publisher='Учебный банк',
        content='Содержательный абзац банковского материала, распознанный со страницы. Его наличие не подтверждает таблицы и графики.',
        published_at=utcnow(),synthetic=True,chunks=[{'text':'Распознанный абзац','page':1,'extraction':'ocr','confidence':90}],
        ingestion_meta={'original_file':'legacy.pdf','page_count':2,'extraction':'ocr'})
    pages=client.get('/api/sources/'+doc.id).json()['ingestion']['pages']
    assert [p['number'] for p in pages]==[1,2]
    assert [p['text_status'] for p in pages]==['ocr','empty']
    assert all(p['numeric_tables_status']=='not_verified' for p in pages)


def test_bank_query_fusion_preserves_retrieval_order_not_random_ids(monkeypatch):
    from app import retrieval
    from types import SimpleNamespace
    rows=[{'id':'z-best','relevance':{'level':'direct'}},{'id':'a-next','relevance':{'level':'direct'}}]
    monkeypatch.setattr(retrieval,'search_documents',lambda *a,**k:rows)
    result=retrieval.bank_sections(None,['Дизель'],SimpleNamespace(title='Дизель',published_at=utcnow(),synthetic=True))
    assert [e['id'] for e in result]==['z-best','a-next']


def test_related_profile_features_invalidate_analysis_cache(client,db):
    from app.models import Event
    user=db.scalar(select(User).where(User.username=='demo'))
    related=Company(id='accessible-small-link',name='Доступный профиль',industry='Логистика',region='Регион',synthetic=True)
    db.add(related)
    db.add(Link(id='small-link',kind='payment',source_id='demo-metal',target_id=related.id,amount=1,count=1))
    user.company_ids=[*user.company_ids,related.id];db.commit()
    event=db.scalar(select(Event).where(Event.synthetic.is_(True)))
    body={'company_id':'demo-metal','event_id':event.id,'role':'CFO'}
    before=client.post('/api/analyses',json=body).json()['run_id']
    related.features={'new_fact':{'value':'Изменилось','source':'fixture','status':'fact'}};db.commit()
    after=client.post('/api/analyses',json=body).json()['run_id']
    assert before!=after


def test_bank_removal_and_replacement_change_evidence_and_cached_analysis(client,db,monkeypatch):
    # A controlled synthesis fixture proves dependency/cache wiring, not model quality.
    from app import agent
    from app.schemas import Claim
    original=agent.demo_insight
    def bank_aware(event,context,role,evidence,question=None):
        insight=original(event,context,role,evidence,question)
        bank=next((e for e in evidence if e['kind']=='bank'),None)
        if bank:
            insight.impact.append(Claim(text='Если компания закупает дизель для автоперевозок, проверить доступность поставок с учётом ремонта заводов. Тип топлива и условия закупок не подтверждены.',
                evidence_ids=[bank['id']],feature_keys=['MAINOKVED_NAME'],assumption=True))
        return insight
    monkeypatch.setattr(agent,'demo_insight',bank_aware)
    from app.ingestion import import_document
    from app.models import Document,Event
    from app.worker import process_one
    from app.db import utcnow
    news,_=import_document(db,title='Экспорт дизельного топлива ограничен',content='Экспорт дизельного топлива временно ограничен. Решение касается поставок дизеля на внешние рынки; внутренних цен и условий договоров сообщение не устанавливает.',
        publisher='Учебная редакция',kind='news',published_at=utcnow(),synthetic=True)
    event=db.scalar(select(Event).where(Event.title==news.title))
    bank,_=import_document(db,title='Обзор дизельного топлива',content='Производство дизельного топлива зависит от загрузки нефтепереработки. Доступность дизеля определяется внутренними поставками и экспортом. Графики ремонта заводов меняют доступные объёмы производства; условия продажи зависят от договоров покупателей топлива.',
        publisher='Учебная аналитика',kind='bank',published_at=utcnow()-timedelta(days=1),synthetic=True)
    body={'company_id':'demo-logistics','role':'TREASURER','event_id':event.id}
    before=client.post('/api/analyses',json=body).json()['run_id'];assert process_one()
    result=client.get('/api/runs/'+before).json()['result']
    assert bank.id in {e['document_id'] for e in result['evidence'] if e['kind']=='bank'}
    assert result['bank_view'],result['limitations']
    db.delete(bank);db.commit()
    gold,_=import_document(db,title='Обзор рынка золота',content='Мировой спрос на золото поддерживается накоплением резервов. Покупатели золотых слитков увеличили закупки; инвесторы оценивают покупки центральных банков и доступность драгоценных металлов.',
        publisher='Учебная аналитика',kind='bank',published_at=utcnow()-timedelta(days=1),synthetic=True)
    after=client.post('/api/analyses',json=body).json()['run_id'];assert after!=before;assert process_one()
    result=client.get('/api/runs/'+after).json()['result']
    assert not result['bank_view']
    assert not any(e['document_id']==gold.id for e in result['evidence'])
