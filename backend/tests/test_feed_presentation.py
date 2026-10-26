from types import SimpleNamespace
from sqlalchemy import select,func
from app.config import settings
from app.db import utcnow
from app.feed_presentation import article_preview,reading_notes
from app.ingestion import import_document
from app.models import Event,Run,User,Usage
from app.semantic_ranking import feed_ranking,REVIEW_VERSION


def test_opening_sentences_are_whole_and_source_abbreviations_are_only_explained():
    text='Ставка сохранена на уровне 14,00% годовых. Экономика в 2п26 растет умеренными темпами. Инфляционные ожидания высокие. В 3к26 темпы изменились.'
    doc=SimpleNamespace(content=text,publisher='Банк России',ingestion_meta={'coverage':'article'})
    excerpt=article_preview(doc)
    assert excerpt['summary']=='Ставка сохранена на уровне 14,00% годовых. Экономика в 2п26 растет умеренными темпами.'
    assert excerpt['summary_truncated'] and excerpt['reading_notes']==[{'term':'2п26','meaning':'2-е полугодие 2026 года'}]
    assert doc.content==text
    assert len(reading_notes(text,'Банк России'))==2
    long='Операции '+('компании '*90)+'проверены.'
    doc.content=long+' Следующее предложение.'
    assert article_preview(doc)['summary']==long
    doc.content=long
    assert not article_preview(doc)['summary_truncated']


def test_preview_reports_missing_analysis_full_source_and_accessible_history(client,db,monkeypatch):
    text='Экономика в 2п26 растет умеренными темпами. '+('Проверочный доступный текст источника для чтения без модели. '*12)+'Последний абзац сохранён целиком.'
    doc,_=import_document(db,title='Проверка полного чтения',content=text,kind='news',publisher='Банк России',published_at=utcnow())
    event=next(e for e in db.scalars(select(Event)) if doc.id in e.document_ids)
    monkeypatch.setattr(settings(),'preview_cached_only',True)
    params={'company_id':'demo-metal','role':'CFO','corpus':'real','scope':'all'}
    feed=client.get('/api/feed',params=params).json();card=feed['items'][0]
    assert feed['processing']=={'analysis_mode':'saved_only','news_updates':False}
    assert card['analysis']['status']=='unavailable'
    source=client.get('/api/sources/'+doc.id).json()
    assert source['content']==text and source['reading_notes'][0]['term']=='2п26'
    assert client.post('/api/analyses',json={'company_id':'demo-metal','event_id':event.id,'role':'CFO'}).status_code==409
    user=db.scalar(select(User).where(User.username=='demo'))
    run=Run(user_id=user.id,company_id='demo-metal',event_id=event.id,role='CFO',access_scope=user.company_ids,
            cache_key='saved-reading-example',status='completed',result={'mode':'live'})
    db.add(run);db.commit()
    card=client.get('/api/feed',params=params).json()['items'][0]
    assert card['analysis']['status']=='saved' and card['analysis']['run_id']==run.id
    assert client.get('/api/feed',params=params|{'role':'CEO'}).json()['items'][0]['analysis']['status']=='unavailable'
    run.access_scope=[*user.company_ids,'inaccessible-company'];db.commit()
    assert client.get('/api/feed',params=params).json()['items'][0]['analysis']['status']=='unavailable'
    assert db.scalar(select(func.count()).select_from(Usage))==0


def test_relation_label_comes_from_saved_model_grade_not_a_constant():
    for grade,level in [(0,'unknown'),(1,'indirect'),(2,'direct')]:
        row=SimpleNamespace(status='completed',result={'review':{'version':REVIEW_VERSION},
            'roles':{'CFO':{'score':grade*30,'relevance':grade,'reason':'Проверенное основание'}},
            'feature_keys':[],'topics':[],'grounds':[],'model_id':'saved-model'})
        assert feed_ranking(row,'CFO')['exposure']['level']==level
