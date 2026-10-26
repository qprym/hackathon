from copy import deepcopy
from sqlalchemy import select
import pytest
from app import reading_list as rl, semantic_ranking as sr
from app.config import settings
from app.models import User,Company,RankingJob,Document
from test_semantic_ranking import real_article,output


@pytest.fixture(autouse=True)
def mocked_review_budget(monkeypatch):
    # Model transport is replaced below; gateway budgets have separate concurrent tests.
    monkeypatch.setattr(rl,'affordable_review_tokens',lambda *a,**kw:kw['preferred'])


def prepare(db,monkeypatch):
    monkeypatch.setattr(settings(),'demo_mode',False)
    user=db.scalar(select(User).where(User.username=='demo'));company=db.get(Company,'demo-metal')
    text=('Полный контекст статьи, включая все её оговорки. '*1500)+'Последний абзац не обрезается.'
    doc,event=real_article(db,title='Завод модернизирует производство',text=text)
    monkeypatch.setattr(sr,'complete_json',lambda policy,payload,**kw:output(payload,1))
    q=sr.enqueue(db,user,company,[event]);sr.process_one(q['job_ids'][0]);db.expire_all()
    return user,company,doc,event,text


def selection(payload):
    if 'review_schema' in payload:
        return {role:{'verdict':'approved','reason':'Источники и применимость к роли проверены.','replacement':None} for role in sr.ROLES}
    a=payload['articles'][0];d=a['documents'][0]
    choice={'article_id':a['article_id'],'reason':'Для этой роли полезно проверить применимость инвестиционного сценария.',
        'feature_key':'MAINOKVED_NAME','source_id':d['source_id'],'quote':d['text'][-100:]}
    return {role:[dict(choice)] for role in sr.ROLES}


def test_listwise_full_sources_two_calls_and_read_only_cache(client,db,monkeypatch):
    user,company,doc,event,text=prepare(db,monkeypatch);seen=[]
    def respond(policy,payload,**kw):
        seen.append(deepcopy(payload));return selection(payload)
    monkeypatch.setattr(rl,'complete_json',respond)
    q=rl.enqueue(db,user,company);assert sr.process_one(q['job_id']);db.expire_all()
    assert len(seen)==2 and 'draft' in seen[1]
    assert all(p['articles'][0]['documents'][0]['text']==text for p in seen)
    for role in sr.ROLES:
        result=client.get('/api/feed',params={'company_id':company.id,'role':role}).json()
        assert result['ordering_version']==rl.VERSION and result['list_selection']['status']=='completed'
        assert result['items'][0]['score']==30
        assert result['items'][0]['reasons']==[selection(seen[0])[role][0]['reason']]
    assert rl.enqueue(db,user,company)['max_provider_calls']==0 and len(seen)==2
    doc.content+=' Изменение полного текста.';doc.content_hash='changed';db.commit()
    assert client.get('/api/feed',params={'company_id':company.id}).json()['list_selection']['status']=='not_requested'


@pytest.mark.parametrize('error',['quote','unknown','duplicate','zero','feature'])
def test_listwise_strict_grounding_and_role_validation(client,db,monkeypatch,error):
    user,company,*_=prepare(db,monkeypatch);payload=rl.from_database(db,user,company);raw=selection(payload)
    if error=='quote':raw['CFO'][0]['quote']='Несуществующая цитата о прибыли'
    if error=='unknown':raw['CFO'][0]['article_id']='missing'
    if error=='duplicate':raw['CFO']*=2
    if error=='zero':payload['articles'][0]['roles']['CFO']['relevance']=0
    if error=='feature':raw['CFO'][0]['feature_key']='INVENTED'
    with pytest.raises(ValueError):rl.validate(raw,payload)


def test_failed_review_never_publishes_or_retries(client,db,monkeypatch):
    user,company,*_=prepare(db,monkeypatch);seen=[]
    def respond(policy,payload,**kw):
        seen.append(payload);raw=selection(payload)
        if 'draft' in payload:
            replacement=selection({k:v for k,v in payload.items() if k!='review_schema'})['CFO']
            replacement[0]['quote']='Выдуманная цитата второго прохода'
            raw['CFO']={'verdict':'corrected','reason':'Применимость исправлена по источнику.','replacement':replacement}
        return raw
    monkeypatch.setattr(rl,'complete_json',respond)
    q=rl.enqueue(db,user,company);sr.process_one(q['job_id']);db.expire_all()
    job=db.get(RankingJob,q['job_id']);assert job.status=='failed' and 'review' in job.response
    assert not sr.process_one(q['job_id']) and len(seen)==2
    result=client.get('/api/feed',params={'company_id':company.id}).json()
    assert result['ordering_version']!=rl.VERSION and result['list_selection']['status']=='failed'
    assert rl.enqueue(db,user,company)['cached'] is True
    retry=rl.enqueue(db,user,company,retry_failed=True)
    assert retry['cached'] is False and retry['job_id']!=job.id
    assert db.get(RankingJob,job.id).status=='failed' and len(seen)==2


def test_changed_profile_blocks_queued_request(client,db,monkeypatch):
    user,company,*_=prepare(db,monkeypatch);q=rl.enqueue(db,user,company)
    company.name+=' изменено';db.commit()
    monkeypatch.setattr(rl,'complete_json',lambda *a,**kw:pytest.fail('Stale context sent'))
    sr.process_one(q['job_id']);db.expire_all();assert db.get(RankingJob,q['job_id']).status=='failed'


def test_offline_endpoint_and_access_scope(client,db):
    assert client.post('/api/reading-list',json={'company_id':'demo-metal'}).status_code==409
    assert client.post('/api/reading-list',json={'company_id':'not-authorized'}).status_code in (403,404)


def test_empty_review_is_valid_and_never_filled_with_old_scores(client,db,monkeypatch):
    user,company,*_=prepare(db,monkeypatch)
    monkeypatch.setattr(rl,'complete_json',lambda policy,payload,**kw:selection(payload) if 'review_schema' in payload else {role:[] for role in sr.ROLES})
    q=rl.enqueue(db,user,company);sr.process_one(q['job_id'])
    result=client.get('/api/feed',params={'company_id':company.id}).json()
    assert result['list_selection']['status']=='completed' and result['items']==[]


def test_older_edition_rejected_but_history_is_preserved(client,db,monkeypatch):
    user,company,*_=prepare(db,monkeypatch);payload=rl.from_database(db,user,company)
    old=payload['articles'][0];old['series_key']='same-publisher-heading';old['published_at']='2026-10-01T00:00:00'
    new=deepcopy(old);new.update(article_id='latest',event_id='new-event',published_at='2026-10-21T00:00:00',event_group='new-group')
    payload['articles'].append(new)
    with pytest.raises(ValueError,match='старый выпуск'):rl.validate(selection(payload),payload)
    raw=selection(payload)
    for role in sr.ROLES:raw[role][0]['article_id']='latest'
    assert all(c[0]['event_id']=='new-event' for c in rl.validate(raw,payload).values())


def test_review_resume_reuses_valid_draft_and_sends_only_one_call(client,db,monkeypatch):
    user,company,*_=prepare(db,monkeypatch);q=rl.enqueue(db,user,company);job=db.get(RankingJob,q['job_id'])
    job.status='failed';job.response={'draft':selection(job.payload)};db.commit();seen=[]
    def respond(policy,payload,**kw):seen.append(payload);return selection(payload)
    monkeypatch.setattr(rl,'complete_json',respond)
    resumed=rl.enqueue_review(db,user,job.id);sr.process_one(resumed['job_id']);db.expire_all()
    assert resumed['max_provider_calls']==1 and len(seen)==1 and 'review_schema' in seen[0]
    assert db.get(RankingJob,resumed['job_id']).status=='completed'
    assert db.get(RankingJob,job.id).status=='failed'


def test_review_cannot_approve_and_replace_at_once(client,db,monkeypatch):
    user,company,*_=prepare(db,monkeypatch);payload=rl.from_database(db,user,company);draft=selection(payload)
    raw=selection({**payload,'review_schema':{}});raw['CFO']['replacement']=[]
    with pytest.raises(ValueError):rl.reviewed_output(raw,draft,payload)


def test_saved_review_normalizes_only_approval_null_and_keeps_long_reason(client,db,monkeypatch):
    user,company,*_=prepare(db,monkeypatch);q=rl.enqueue(db,user,company);job=db.get(RankingJob,q['job_id'])
    draft=selection(job.payload);raw={r:{'verdict':'approved','reason':'Подробное объяснение проверки. '*50} for r in sr.ROLES}
    job.status='failed';job.error='Previous format error';job.response={'draft':draft,'review':raw};db.commit()
    monkeypatch.setattr(rl,'complete_json',lambda *a,**kw:pytest.fail('Offline validation made a call'))
    rl.revalidate_saved(db,user,job.id)
    assert job.status=='completed' and job.response['review']==raw and job.response['validated_offline']
    assert 'replacement' not in raw['CFO'] and job.response['previous_validation_error']=='Previous format error'
    raw['CFO']['verdict']='corrected'
    with pytest.raises(ValueError):rl.reviewed_output(raw,draft,job.payload)
