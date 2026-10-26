from datetime import timedelta
from sqlalchemy import select
from app.config import settings,environment_settings
from app.db import utcnow
from app.models import User,Company,Document,RankingJob,Usage,RelevanceAssessment
from app import semantic_ranking as sr
from app.pipeline import schedule
from test_semantic_ranking import real_article,output


def test_remote_automatic_is_explicit_persisted_and_save_does_not_call_provider(client,db,monkeypatch,tmp_path):
    monkeypatch.setattr(environment_settings(),'llm_settings_path',str(tmp_path/'runtime.json'))
    data=client.get('/api/admin/llm-settings').json()
    body={k:v for k,v in data.items() if k not in ('source','approved_models','api_key_configured')}
    body.update(enabled=True,automatic=True,provider_mode='remote',base_url='https://api.deepseek.com',api_key='fake-key',
        analysis_model='DeepSeek-V4.1-Flash',extraction_model='DeepSeek-V4.1-Flash',analysis_id='deepseek-flash',extraction_id='deepseek-flash',
        input_rub_per_million=30,output_rub_per_million=120,test_limit_rub=100,request_limit=161,daily_limit_rub=100)
    response=client.post('/api/admin/llm-settings',json=body)
    assert response.status_code==200,response.text
    boundary=settings().auto_personalization_started_at
    assert boundary and response.json()['automatic'] and not db.scalars(select(Usage)).all()
    body['revision']=response.json()['revision']
    assert client.post('/api/admin/llm-settings',json=body).status_code==200
    assert settings().auto_personalization_started_at==boundary
    from app.llm import block_provider,provider_pause,PROVIDER_FUNDS_ERROR
    block_provider(db);db.commit()
    assert provider_pause(db) and schedule()==[]
    user=db.scalar(select(User).where(User.username=='demo'))
    job=RankingJob(user_id=user.id,company_id='demo-metal',status='failed',error=PROVIDER_FUNDS_ERROR,payload={},cache_keys=[])
    quota_job=RankingJob(user_id=user.id,company_id='demo-metal',status='failed',error='Общий лимит запросов или денежный лимит теста исчерпан.',payload={},cache_keys=[])
    db.add_all([job,quota_job]);db.commit()
    body['revision']=client.get('/api/admin/llm-settings').json()['revision'];body['active_company_ids']='demo-metal'
    assert client.post('/api/admin/llm-settings',json=body).status_code==200
    db.expire_all()
    assert not provider_pause(db) and db.get(RankingJob,job.id).status=='queued'
    assert db.get(RankingJob,quota_job.id).status=='queued'
    assert not db.scalars(select(Usage)).all()


def test_remote_scheduler_only_new_documents_bounded_idempotent_and_reviewed(client,db,monkeypatch):
    user=db.scalar(select(User).where(User.username=='demo'));company=db.get(Company,'demo-metal')
    db.scalar(select(User).where(User.username=='viewer')).company_ids=[]
    old_doc,_=real_article(db,title='Архивная публикация',text='Старый материал о производстве и закупках. '*8)
    old_doc.created_at=utcnow()-timedelta(days=1);db.commit()
    boundary=utcnow().isoformat()
    events=[real_article(db,title=f'Новое событие {i}',text=f'Выпуск {i}. '+'Материал о производстве и закупках. '*8)[1] for i in range(6)]
    for key,value in dict(demo_mode=False,auto_personalization=True,neural_ranking_worker=True,
        llm_provider_mode='remote',llm_base_url='https://api.deepseek.com',active_company_ids=company.id,
        auto_personalization_started_at=boundary).items():monkeypatch.setattr(settings(),key,value)
    schedule();schedule()
    jobs=db.scalars(select(RankingJob)).all()
    assert len(jobs)==1 and len(jobs[0].payload['articles'])==5
    assert {a['event_id'] for a in jobs[0].payload['articles']}<={e.id for e in events}
    monkeypatch.setattr(sr,'complete_json',lambda policy,p,**kw:output(p,1))
    assert sr.process_one()
    db.expire_all()
    assert all(r.result['review']['version']==sr.REVIEW_VERSION for r in db.scalars(select(RelevanceAssessment)))
    schedule();schedule();assert sr.process_one();db.expire_all()
    count=len(db.scalars(select(RankingJob)).all());schedule();schedule()
    assert len(db.scalars(select(RankingJob)).all())==count
    assert all(j.payload.get('purpose')!='full_feed' for j in db.scalars(select(RankingJob)))
    assert not db.scalars(select(Usage)).all()


def test_old_reviewed_scores_remain_visible_but_are_not_current_after_connection_change(client,db,monkeypatch):
    user=db.scalar(select(User).where(User.username=='demo'));company=db.get(Company,'demo-metal')
    _,event=real_article(db)
    monkeypatch.setattr(settings(),'demo_mode',False)
    monkeypatch.setattr(sr,'complete_json',lambda policy,p,**kw:output(p,1))
    sr.enqueue(db,user,company,[event]);assert sr.process_one()
    monkeypatch.setattr(settings(),'llm_model_revision','new-connection')
    feed=client.get('/api/feed',params={'company_id':company.id}).json()
    assert feed['selection']['completed']==0 and feed['selection']['historical']==1
    assert feed['items'][0]['ranking_historical'] and feed['personalization']['status']=='partial'
    # A changed company profile must never inherit those historical conclusions.
    company.industry='Иная отрасль';db.commit()
    feed=client.get('/api/feed',params={'company_id':company.id}).json()
    assert feed['selection']['historical']==0


def test_resume_review_uses_saved_draft_without_second_selection_call(client,db,monkeypatch):
    user=db.scalar(select(User).where(User.username=='demo'));company=db.get(Company,'demo-metal')
    _,event=real_article(db)
    monkeypatch.setattr(settings(),'demo_mode',False)
    monkeypatch.setattr(sr,'complete_json',lambda policy,p,**kw:output(p,1))
    sr.enqueue(db,user,company,[event]);assert sr.process_one(defer_review=True)
    original=db.scalar(select(RankingJob));calls=[]
    def review(policy,p,**kwargs):
        assert 'review_schema' in p
        calls.append(p);return output(p,1)
    monkeypatch.setattr(sr,'complete_json',review)
    job=RankingJob(user_id=user.id,company_id=company.id,cache_keys=original.cache_keys,
        payload={'purpose':'resume_selection_review','context':original.payload['context'],
                 'provider_mode':settings().llm_provider_mode,'model_revision':settings().llm_model_revision})
    db.add(job);db.commit()
    assert sr.process_one(job.id);db.expire_all()
    assert len(calls)==1 and db.get(RankingJob,job.id).status=='completed'
    assert db.scalar(select(RelevanceAssessment)).result['review']['version']==sr.REVIEW_VERSION
