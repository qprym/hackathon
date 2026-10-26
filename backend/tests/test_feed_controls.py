from datetime import timedelta
import pytest
from sqlalchemy import select,func
from app.config import settings,environment_settings
from app.db import utcnow
from app.models import FeedState,Usage
from app.ingestion import import_document
from app.feeds import feed_loop


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch,tmp_path):
    monkeypatch.setattr(environment_settings(),'llm_settings_path',str(tmp_path/'runtime.json'))


def test_sort_is_global_stable_across_pages_and_bound_to_snapshot(client,db):
    for i in range(8):
        import_document(db,title=f'Проверка порядка {i}',content=f'Синтетический текст о сроках платежей и ликвидности компании. Экземпляр {i}.',
                        kind='news',publisher='Проверка',published_at=utcnow()-timedelta(days=i),synthetic=True)
    params={'company_id':'demo-metal','corpus':'synthetic','scope':'all','limit':2}
    for sort in ['newest','oldest']:
        first=client.get('/api/feed',params=params|{'sort':sort}).json();rows=list(first['items']);page=first
        while page['next_offset'] is not None:
            page=client.get('/api/feed',params=params|{'sort':sort,'feed_version':first['feed_version'],'offset':page['next_offset']}).json()
            rows.extend(page['items'])
        keys=[(r['published_at'],r['id']) for r in rows]
        assert keys==sorted(keys,reverse=sort=='newest') and len(set(r['id'] for r in rows))==first['total']
        assert client.get('/api/feed',params=params|{'sort':'relevance','feed_version':first['feed_version'],'offset':2}).status_code==409
    assert client.get('/api/feed',params=params|{'sort':'bad'}).status_code==422


def test_rss_settings_preserve_llm_credentials_and_reset_is_independent(client,db):
    connection=client.get('/api/admin/llm-settings').json()
    connection={k:v for k,v in connection.items() if k not in ('source','approved_models','api_key_configured')}
    connection.update(provider_mode='local',base_url='http://llm:8000/v1',analysis_id='local-model',extraction_id='local-model',api_key='test-local-credential',enabled=True)
    assert client.post('/api/admin/llm-settings',json=connection).status_code==200
    identity=settings().llm_model_revision
    db.add(FeedState(key='cbr',status='ok',report={},last_finished_at=utcnow(),next_refresh_at=utcnow()+timedelta(days=1)));db.commit()
    current=client.get('/api/admin/feed-settings').json()
    body={'revision':current['revision'],'automatic':True,'interval_seconds':120,'sources':['cbr']}
    response=client.post('/api/admin/feed-settings',json=body)
    assert response.status_code==200,response.text
    assert settings().llm_model_revision==identity and settings().llm_local_api_key=='test-local-credential'
    assert 'test-local-credential' not in response.text
    status=client.get('/api/feeds/status').json()
    assert status['automatic'] and next(x for x in status['items'] if x['key']=='cbr')['scheduled']
    assert not next(x for x in status['items'] if x['key']=='vedomosti')['scheduled']
    db.expire_all();assert db.get(FeedState,'cbr').next_refresh_at<=utcnow()
    revision=client.get('/api/admin/llm-settings').json()['revision']
    assert client.post('/api/admin/llm-settings/reset',json={'revision':revision}).status_code==200
    assert settings().auto_fetch_rss and settings().rss_sources==['cbr'] and settings().demo_mode
    assert db.scalar(select(func.count()).select_from(Usage))==0


def test_feed_settings_validation_permissions_and_paused_dates(client,db):
    current=client.get('/api/admin/feed-settings').json()
    body={'revision':current['revision'],'automatic':True,'interval_seconds':120,'sources':['cbr']}
    for change in [{'sources':[]},{'sources':['unknown']},{'interval_seconds':0},{'interval_seconds':90000}]:
        assert client.post('/api/admin/feed-settings',json=body|change).status_code==422
    assert client.post('/api/admin/feed-settings',json=body|{'automatic':False}).status_code==200
    assert client.post('/api/admin/feed-settings',json=body).status_code==409
    assert all(item['next_refresh_at'] is None for item in client.get('/api/feeds/status').json()['items'])
    client.post('/api/auth/logout');client.post('/api/auth/login',json={'username':'viewer','password':'demo-alfa-2026'})
    assert client.get('/api/admin/feed-settings').status_code==403
    assert client.post('/api/admin/feed-settings',json=body).status_code==403


def test_scheduler_observes_enable_disable_and_selected_sources_without_restart(monkeypatch):
    cfg=environment_settings();monkeypatch.setattr(cfg,'auto_fetch_rss',False);monkeypatch.setattr(cfg,'rss_sources',['vedomosti'])
    calls=[];monkeypatch.setattr('app.feeds.refresh_feed',lambda key:calls.append(key))
    class Stop:
        ticks=0
        def is_set(self):return self.ticks>=3
        def wait(self,seconds):
            self.ticks+=1;cfg.auto_fetch_rss=self.ticks==1
    feed_loop(Stop())
    assert calls==['vedomosti']
