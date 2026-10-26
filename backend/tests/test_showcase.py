from sqlalchemy import select,func
from app.config import settings
from app.models import Company,Document,Run,Usage,User
from app import semantic_ranking as sr
from app.showcase import bundle
from test_semantic_ranking import real_article,output


def test_nine_ready_examples_are_complete_cited_and_never_call_a_model(client,db,monkeypatch):
    # Even a live deployment can display the static examples without contacting its provider.
    monkeypatch.setattr(settings(),'demo_mode',False)
    examples=client.get('/api/examples').json()
    assert len(examples['items'])==9
    impacts={}
    for item in examples['items']:
        opened=client.post(f"/api/examples/{item['id']}/open")
        assert opened.status_code==200,opened.text
        run=client.get('/api/runs/'+opened.json()['run_id']).json()
        result=run['result']
        assert run['status']=='completed' and result['mode']=='demo' and result['fixture']=='showcase-v1'
        assert result['verification']=='checked' and result['fixture_notice']
        assert all(result[section] for section in ('facts','bank_view','impact','risks','opportunities','actions'))
        sources={e['id']:e for e in result['evidence']}
        assert all(e['synthetic'] for e in sources.values())
        for section in ('facts','bank_view','impact','risks','opportunities','actions'):
            for claim in result[section]:
                assert claim['evidence_ids'] and set(claim['evidence_ids'])<=sources.keys()
        for e in sources.values():
            source=client.get('/api/sources/'+e['document_id']).json()
            assert e['excerpt'] in source['content']
        impacts.setdefault(item['company_id'],set()).add(result['impact'][0]['text'])
        again=client.post(f"/api/examples/{item['id']}/open").json()
        assert again['cached'] and again['run_id']==opened.json()['run_id']
    assert all(len(texts)==3 for texts in impacts.values())
    assert db.scalar(select(func.count()).select_from(Usage))==0
    assert db.scalar(select(func.count()).select_from(Run))==9


def test_example_access_is_scoped_to_current_user(client,db):
    other=client.post('/api/examples/demo-metal-cfo/open').json()['run_id']
    client.post('/api/auth/logout')
    client.post('/api/auth/login',json={'username':'viewer','password':'demo-alfa-2026'})
    examples=client.get('/api/examples').json()['items']
    assert len(examples)==3 and {e['company_id'] for e in examples}=={'demo-metal'}
    assert client.post('/api/examples/demo-retail-cfo/open').status_code==404
    assert client.get('/api/runs/'+other).status_code==404
    own=client.post('/api/examples/demo-metal-cfo/open').json()['run_id']
    assert own!=other
    assert client.get('/api/runs/'+own).json()['trace']==[]


def test_fixture_does_not_reuse_changed_profile_or_source(client,db):
    company=db.get(Company,'demo-metal')
    original=company.features
    company.features={**original,'CL_PRODUCT_LOA_MARK':{**original['CL_PRODUCT_LOA_MARK'],'value':False}}
    db.commit()
    assert client.post('/api/examples/demo-metal-cfo/open').status_code==409
    company.features=original;db.commit()
    title=bundle()['news'][0]['title']
    document=db.scalar(select(Document).where(Document.title==title))
    document.content='Содержимое учебного источника было заменено.';db.commit()
    assert client.post('/api/examples/demo-metal-cfo/open').status_code==409


def test_unprocessed_feed_is_not_reported_as_checked_irrelevance(client,db,monkeypatch):
    _,event=real_article(db)
    params={'company_id':'demo-metal','role':'CFO','scope':'personal'}
    feed=client.get('/api/feed',params=params).json()
    assert feed['total']==0 and feed['personalization']['status']=='not_processed'
    assert feed['personalization']['article_count']==1
    monkeypatch.setattr(settings(),'demo_mode',False)
    user=db.scalar(select(User).where(User.username=='demo'));company=db.get(Company,'demo-metal')
    monkeypatch.setattr(sr,'complete_json',lambda policy,payload,**kw:output(payload,0))
    for job in sr.enqueue(db,user,company,[event])['job_ids']:sr.process_one(job)
    feed=client.get('/api/feed',params=params).json()
    assert feed['total']==0 and feed['personalization']['status']=='ready'
    assert feed['personalization']['assessed_count']==1


def test_initial_company_choice_can_use_checked_roles_and_invalidates_on_context_change(client,db,monkeypatch):
    monkeypatch.setattr(settings(),'demo_mode',False)
    _,event=real_article(db)
    user=db.scalar(select(User).where(User.username=='demo'));company=db.get(Company,'demo-metal')
    monkeypatch.setattr(sr,'complete_json',lambda policy,payload,**kw:output(payload,2))
    for job in sr.enqueue(db,user,company,[event])['job_ids']:sr.process_one(job)
    rows={c['id']:c for c in client.get('/api/companies').json()}
    assert rows[company.id]['ready_roles']==list(sr.ROLES)
    assert rows['demo-retail']['ready_roles']==[]
    company.region='Изменённый регион';db.commit()
    rows={c['id']:c for c in client.get('/api/companies').json()}
    assert rows[company.id]['ready_roles']==[]


def test_initial_company_choice_recognizes_full_selection_without_preliminary_grades(client,db,monkeypatch):
    from app import full_selection as fs
    from test_complete_feed import response
    monkeypatch.setattr(settings(),'demo_mode',False)
    user=db.scalar(select(User).where(User.username=='demo'));company=db.get(Company,'demo-metal')
    company.synthetic=False;db.commit()
    real_article(db)
    monkeypatch.setattr(fs,'complete_json',lambda policy,packet,**kw:response(packet))
    queued=fs.enqueue(db,user,company)
    sr.process_one(queued['job_id'])
    rows={c['id']:c for c in client.get('/api/companies').json()}
    assert rows[company.id]['ready_roles']==list(sr.ROLES)
