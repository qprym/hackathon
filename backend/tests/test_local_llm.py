import httpx
import pytest
from sqlalchemy import select,func
from app import llm
from app.config import settings
from app.models import LlmAllowance,Budget,Usage


@pytest.fixture
def local(monkeypatch):
    cfg=settings()
    for k,v in dict(demo_mode=False,llm_provider_mode='local',llm_base_url='http://host.docker.internal:8001/v1',
        llm_analysis_id='local-qwen',llm_api_key='remote-key-must-not-be-forwarded',llm_local_api_key='',
        llm_request_limit=0,llm_daily_limit_rub=0,llm_test_limit_rub=0,
        llm_input_rub_per_million=0,llm_output_rub_per_million=0,llm_local_max_tokens=None).items():monkeypatch.setattr(cfg,k,v)
    seen=[]
    def respond(url,**kw):
        seen.append(kw)
        return httpx.Response(200,request=httpx.Request('POST',url),json={
            'usage':{'prompt_tokens':20,'completion_tokens':30},'choices':[{'message':{'content':'{"ok":true}'}}]})
    monkeypatch.setattr(llm.httpx,'post',respond)
    return seen


def test_local_has_no_money_request_or_client_output_cap(local,db):
    db.add(LlmAllowance(key=llm.ALLOWANCE_KEY,requests=999,spent=100));db.commit()
    for _ in range(3):assert llm.complete_json('test',{'full_article':'abc'*10000},max_tokens=1)=={'ok':True}
    assert all('max_tokens' not in r['json'] and r['headers']=={} for r in local)
    assert all('json' in r['json']['messages'][0]['content'].lower() for r in local)
    assert all(r['json']['messages'][1]['content'].count('abc')==10000 for r in local)
    db.expire_all();assert db.get(LlmAllowance,llm.ALLOWANCE_KEY).requests==999
    assert db.get(LlmAllowance,llm.ALLOWANCE_KEY).spent==100
    assert db.scalar(select(func.count()).select_from(Budget))==0
    assert all(u.cost_rub==0 for u in db.scalars(select(Usage)))
    assert llm.allowance_status(db)['budget_enforced'] is False
    assert llm.affordable_review_tokens('test',{},preferred=32768)==32768


def test_local_mode_cannot_bypass_paid_provider_limits(local,monkeypatch):
    monkeypatch.setattr(settings(),'llm_base_url','https://api.deepseek.com')
    with pytest.raises(llm.ModelUnavailable,match='локального'):llm.complete_json('test',{})
    assert local==[]


def test_explicit_local_output_and_local_key_are_separate(local,monkeypatch):
    monkeypatch.setattr(settings(),'llm_local_max_tokens',12345)
    monkeypatch.setattr(settings(),'llm_local_api_key','local-only-key')
    llm.complete_json('test',{},max_tokens=1)
    assert local[0]['json']['max_tokens']==12345
    assert local[0]['headers']=={'Authorization':'Bearer local-only-key'}


def test_local_api_does_not_reject_exhausted_remote_quota(client,db,monkeypatch):
    monkeypatch.setattr(settings(),'llm_provider_mode','local')
    monkeypatch.setattr(settings(),'demo_mode',False)
    monkeypatch.setattr(settings(),'neural_ranking_worker',True)
    monkeypatch.setattr(settings(),'llm_request_limit',0)
    assert client.post('/api/ranking',json={'company_id':'demo-metal'}).status_code==202
