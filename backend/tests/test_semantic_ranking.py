from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app import semantic_ranking as sr
from app.config import settings
from app.db import utcnow
from app.ingestion import import_document
from app.models import Company,Event,RankingJob,RelevanceAssessment,User


def real_article(db,title='Главным результатом стали договорённости',text=None):
    doc,_=import_document(db,title=title,content=text or ('Президент Франции договорился о поставках газа. '*3),
        kind='news',publisher='Редакция',published_at=utcnow(),synthetic=False)
    event=next(e for e in db.scalars(select(Event)) if doc.id in e.document_ids)
    return doc,event


def output(payload,relevance=0):
    if 'review_schema' in payload:
        return {'checks':[{'article_id':a['article_id'],'verdict':'supported','reason':'Основания и границы применимости проверены.','replacement':None} for a in payload['articles']]}
    rows=[]
    for article in payload['articles']:
        grade={'relevance':relevance,'score':70 if relevance==2 else 30 if relevance else 0,
               'reason':'Связь с известными операциями компании не установлена.' if not relevance else 'Событие применимо к указанному отраслевому признаку компании.'}
        rows.append({'article_id':article['article_id'],'topics':['demand'] if relevance else [],
            'feature_keys':['MAINOKVED_NAME'] if relevance else [],
            'grounds':[{'source_id':article['documents'][0]['source_id'],'quote':article['documents'][0]['text'][-100:]}] if relevance else [],
            **{role:dict(grade) for role in sr.ROLES}})
    return {'assessments':rows}


def test_model_reads_full_text_and_all_roles_reuse_one_cache(client,db,monkeypatch):
    monkeypatch.setattr(settings(),'demo_mode',False)
    text=('Контекст статьи без сокращений. '*1200)+'Последняя оговорка тоже должна попасть модели.'
    doc,event=real_article(db,text=text);user=db.scalar(select(User).where(User.username=='demo'));company=db.get(Company,'demo-metal')
    queued=sr.enqueue(db,user,company,[event]);seen=[]
    def respond(policy,payload,**kwargs):
        assert len(kwargs['run_id'])==36
        seen.append(deepcopy(payload));return output(payload,2)
    monkeypatch.setattr(sr,'complete_json',respond)
    assert sr.process_one(queued['job_ids'][0])
    assert len(seen)==2 and all(s['articles'][0]['documents'][0]['text']==text for s in seen)
    assert set(seen[0]['context']['features'])>=set(company.features)
    for role in sr.ROLES:
        feed=client.get('/api/feed',params={'company_id':company.id,'role':role}).json()
        assert feed['items'][0]['ranking_method']=='llm'
        assert feed['items'][0]['score']==70
    assert sr.enqueue(db,user,company,[event])['max_provider_calls']==0
    assert len(seen)==2
    company.name+=' изменено';db.commit()
    assert not client.get('/api/feed',params={'company_id':company.id}).json()['items']


def test_no_rule_fallback_for_unassessed_real_news(client,db):
    _,event=real_article(db,'Ключевая ставка изменилась')
    assert not client.get('/api/feed',params={'company_id':'demo-metal'}).json()['items']
    search=client.get('/api/feed',params={'company_id':'demo-metal','q':'Ключевая ставка'}).json()
    assert search['items'][0]['ranking_status']=='not_requested'
    assert search['items'][0]['score']==0 and search['selection']['not_requested']==1


def test_fake_quote_is_rejected_and_raw_response_retained_without_retry(client,db,monkeypatch):
    monkeypatch.setattr(settings(),'demo_mode',False)
    _,event=real_article(db);user=db.scalar(select(User).where(User.username=='demo'))
    queued=sr.enqueue(db,user,db.get(Company,'demo-metal'),[event]);calls=[]
    def respond(policy,payload,**kwargs):
        raw=output(payload,2);raw['assessments'][0]['grounds'][0]['quote']='Несуществующая цитата, которой нет в исходном тексте.'
        calls.append(raw);return raw
    monkeypatch.setattr(sr,'complete_json',respond)
    assert sr.process_one(defer_review=True)
    assert not sr.process_one()
    db.expire_all();row=db.scalar(select(RelevanceAssessment));job=db.get(RankingJob,queued['job_ids'][0])
    assert row.status=='failed' and job.response==calls[0] and len(calls)==1
    assert not client.get('/api/feed',params={'company_id':'demo-metal'}).json()['items']


def test_missing_roles_cannot_publish_partial_model_schema():
    with pytest.raises(ValueError):sr.BatchResult.model_validate({'assessments':[{'article_id':'N1','CEO':{'score':1}}]})


def test_quote_normalization_changes_only_whitespace():
    text='Банк\u00a0России\nсохранил ставку.'
    assert sr.exact_quote(text,'Банк России сохранил ставку.')==text
    assert sr.exact_quote(text,'Банк России повысил ставку.') is None


def test_exact_source_title_is_valid_ground_but_paraphrase_is_not():
    article={'article_id':'N1','documents':[{'source_id':'N1D1','title':'Банк России сохранил ключевую ставку',
        'text':'Совет директоров принял решение.','content_hash':'x','publisher':'Банк России','url':'https://example.org'}]}
    context={'features':{'MAINOKVED_NAME':{'value':'Производство'}}}
    raw=output({'articles':[{**article,'documents':[{**article['documents'][0],'text':'Банк России сохранил ключевую ставку'}]}]},2)['assessments'][0]
    result=sr.validate_assessment(sr.Assessment.model_validate(raw),article,context)
    assert result['grounds'][0]['location']=='title'
    raw['grounds'][0]['quote']='Банк России повысил ключевую ставку'
    with pytest.raises(ValueError):sr.validate_assessment(sr.Assessment.model_validate(raw),article,context)


def test_unreviewed_draft_cannot_enter_personal_feed():
    row=SimpleNamespace(status='completed',result={'roles':{'CFO':{'score':100,'relevance':2,'reason':'Непроверенный вывод'}}})
    assert sr.feed_ranking(row,'CFO')['eligible'] is False


def test_only_redundant_empty_role_fields_are_normalized():
    payload={'articles':[{'article_id':'N1','documents':[]}]}
    raw=output(payload)
    raw['assessments'][0]['CEO'].update(feature_keys=[],grounds=[])
    parsed=sr.parse_batch(raw)
    assert parsed.assessments[0].CEO.score==0
    assert 'grounds' in raw['assessments'][0]['CEO']  # original preserved
    raw['assessments'][0]['CEO']['feature_keys']=['INVENTED']
    with pytest.raises(ValueError):sr.parse_batch(raw)


def test_review_cannot_approve_fabricated_quote(client,db,monkeypatch):
    monkeypatch.setattr(settings(),'demo_mode',False)
    _,event=real_article(db);user=db.scalar(select(User).where(User.username=='demo'))
    q=sr.enqueue(db,user,db.get(Company,'demo-metal'),[event])
    def respond(policy,payload,**kwargs):
        raw=output(payload,2)
        if 'assessments' in raw:raw['assessments'][0]['grounds'][0]['quote']='Такой цитаты в источнике нет.'
        return raw
    monkeypatch.setattr(sr,'complete_json',respond)
    sr.process_one(q['job_ids'][0]);db.expire_all()
    assert db.scalar(select(RelevanceAssessment)).status=='failed'
    assert not client.get('/api/feed',params={'company_id':'demo-metal'}).json()['items']


def test_lost_lease_never_makes_another_paid_call(client,db,monkeypatch):
    monkeypatch.setattr(settings(),'demo_mode',False)
    _,event=real_article(db);user=db.scalar(select(User).where(User.username=='demo'))
    q=sr.enqueue(db,user,db.get(Company,'demo-metal'),[event]);job=db.get(RankingJob,q['job_ids'][0])
    job.status='running';job.lease_until=utcnow()-timedelta(seconds=1);db.commit()
    monkeypatch.setattr(sr,'complete_json',lambda *a,**kw:pytest.fail('No paid retry'))
    assert not sr.process_one()
    db.expire_all();assert db.get(RankingJob,job.id).status=='failed'


def test_lost_review_lease_marks_draft_failed_without_retry(client,db,monkeypatch):
    monkeypatch.setattr(settings(),'demo_mode',False)
    _,event=real_article(db);user=db.scalar(select(User).where(User.username=='demo'))
    q=sr.enqueue(db,user,db.get(Company,'demo-metal'),[event]);parent=db.get(RankingJob,q['job_ids'][0]);parent.status='completed'
    review=RankingJob(user_id=user.id,company_id=parent.company_id,payload={'purpose':'selection_review'},cache_keys=parent.cache_keys,
                      status='running',lease_until=utcnow()-timedelta(seconds=1))
    db.add(review);db.flush();row=db.scalar(select(RelevanceAssessment));row.status='reviewing';row.result={'pending_review_job':review.id};db.commit()
    monkeypatch.setattr(sr,'complete_json',lambda *a,**kw:pytest.fail('No paid retry'))
    assert not sr.process_one()
    db.expire_all();assert row.status=='failed'


def test_enqueue_limits_new_batches_to_remaining_calls(client,db):
    events=[real_article(db,title=f'Новость {i}',text=(f'Уникальное сообщение {i}. '*12))[1] for i in range(7)]
    user=db.scalar(select(User).where(User.username=='demo'))
    result=sr.enqueue(db,user,db.get(Company,'demo-metal'),events,max_jobs=1)
    assert result['articles_queued']==5 and result['deferred_by_quota']==2
    assert result['max_provider_calls']==2 and len(result['job_ids'])==1
