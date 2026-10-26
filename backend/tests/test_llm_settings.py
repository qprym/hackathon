import json
from pathlib import Path
import pytest
from sqlalchemy import select,func
from app.config import settings,environment_settings,settings_scope
from app.models import Audit,Run,Usage,LlmAllowance,User
from app import llm


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch,tmp_path):
    path=tmp_path/'runtime'/'llm.json'
    monkeypatch.setattr(environment_settings(),'llm_settings_path',str(path))
    return path


def body(client,**changes):
    data=client.get('/api/admin/llm-settings').json()
    return {k:v for k,v in data.items() if k not in ('source','approved_models','api_key_configured')} | changes


def test_token_is_persisted_never_returned_or_logged_and_worker_reads_it(client,db,isolated_settings):
    secret='test-secret-for-runtime-settings'
    before=client.get('/api/admin/metrics').json()['llm_allowance']
    response=client.post('/api/admin/llm-settings',json=body(client,provider_mode='local',
        base_url='http://host.docker.internal:8001/v1',analysis_id='served-qwen',extraction_id='served-qwen',api_key=secret))
    assert response.status_code==200,response.text
    assert response.json()['api_key_configured'] and secret not in response.text
    assert secret not in client.get('/api/admin/llm-settings').text
    assert isolated_settings.exists() and secret in isolated_settings.read_text()
    assert settings().llm_local_api_key==secret and not settings().llm_api_key
    assert secret not in json.dumps([a.details for a in db.scalars(select(Audit))])
    assert before==client.get('/api/admin/metrics').json()['llm_allowance'] | {'provider_mode':before['provider_mode'],'budget_enforced':before['budget_enforced']}
    assert db.scalar(select(func.count()).select_from(Usage))==0
    assert client.post('/api/admin/llm-settings',json=body(client,api_key=None)).json()['api_key_configured']


def test_credential_never_follows_changed_address_or_provider(client,isolated_settings):
    secret='original-server-key'
    assert client.post('/api/admin/llm-settings',json=body(client,base_url='https://api.example.invalid/v1',api_key=secret)).status_code==200
    response=client.post('/api/admin/llm-settings',json=body(client,base_url='https://different.example.invalid/v1'))
    assert response.status_code==200 and not response.json()['api_key_configured']
    assert secret not in isolated_settings.read_text()
    response=client.post('/api/admin/llm-settings',json=body(client,provider_mode='local',base_url='http://llm:8000/v1'))
    assert response.status_code==200 and not response.json()['api_key_configured']


def test_no_viewer_access_no_reflected_tokens_and_conflicting_updates_rejected(client):
    old=body(client)
    secret='do-not-reflect-this-token'
    response=client.post('/api/admin/llm-settings',json={**old,'api_key':secret,'timeout_seconds':'wrong'})
    assert response.status_code==422 and secret not in response.text
    assert client.post('/api/admin/llm-settings',json=old).status_code==200
    assert client.post('/api/admin/llm-settings',json=old).status_code==409
    client.post('/api/auth/logout')
    client.post('/api/auth/login',json={'username':'viewer','password':'demo-alfa-2026'})
    assert client.get('/api/admin/llm-settings').status_code==403
    assert client.post('/api/admin/llm-settings',json=old).status_code==403
    assert client.post('/api/admin/llm-settings/reset',json={'revision':'environment'}).status_code==403


def test_runtime_snapshot_is_stable_during_change_and_reset_preserves_ledger(client,db,isolated_settings):
    db.add(LlmAllowance(key=llm.ALLOWANCE_KEY,requests=7,spent=3.2));db.commit()
    first=body(client,provider_mode='local',enabled=True,base_url='http://llm:8000/v1',analysis_id='v1',extraction_id='v1')
    assert client.post('/api/admin/llm-settings',json=first).status_code==200
    cfg=settings();revision=cfg.llm_model_revision
    with settings_scope():
        document=json.loads(isolated_settings.read_text())
        document['overrides']['llm_analysis_id']='v2'
        isolated_settings.write_text(json.dumps(document))
        assert settings().llm_analysis_id=='v1' and settings().llm_model_revision==revision
    assert settings().llm_analysis_id=='v2' and settings().llm_model_revision!=revision
    response=client.post('/api/admin/llm-settings/reset',json={'revision':document['revision']})
    assert response.status_code==200 and response.json()['source']=='environment'
    assert not isolated_settings.exists()
    db.expire_all();ledger=db.get(LlmAllowance,llm.ALLOWANCE_KEY)
    assert (ledger.requests,ledger.spent)==(7,3.2)


def test_invalid_endpoints_budgets_and_active_jobs_are_rejected(client,db):
    for patch in ({'base_url':'https://user:secret@example.invalid/v1'},
                  {'provider_mode':'local','base_url':'https://api.deepseek.com'},
                  {'base_url':'http://api.example.invalid'},
                  {'enabled':True,'base_url':'https://api.example.invalid/v1','api_key':'test-token','analysis_id':'a','extraction_id':'a'},
                  {'automatic':True}):
        assert client.post('/api/admin/llm-settings',json=body(client,**patch)).status_code==422
    event=client.get('/api/feed',params={'company_id':'demo-metal','corpus':'synthetic'}).json()['items'][0]
    client.post('/api/analyses',json={'company_id':'demo-metal','event_id':event['id'],'role':'CFO'})
    assert client.post('/api/admin/llm-settings',json=body(client)).status_code==409


def test_worker_gateway_uses_saved_local_token_without_remote_quota(client,db,monkeypatch):
    import httpx
    secret='local-worker-test-key'
    assert client.post('/api/admin/llm-settings',json=body(client,enabled=True,provider_mode='local',
        base_url='http://llm:8000/v1',analysis_id='served-local',extraction_id='served-local',api_key=secret,
        request_limit=0,test_limit_rub=0,daily_limit_rub=0)).status_code==200
    def respond(url,**kwargs):
        assert url=='http://llm:8000/v1/chat/completions'
        assert kwargs['headers']=={'Authorization':'Bearer '+secret}
        assert kwargs['json']['model']=='served-local'
        return httpx.Response(200,request=httpx.Request('POST',url),json={
            'usage':{'prompt_tokens':1,'completion_tokens':1},'choices':[{'message':{'content':'{"ok":true}'}}]})
    monkeypatch.setattr(llm.httpx,'post',respond)
    assert llm.complete_json('Return JSON',{})=={'ok':True}
    assert db.get(LlmAllowance,llm.ALLOWANCE_KEY) is None
