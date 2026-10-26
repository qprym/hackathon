from datetime import datetime
from types import SimpleNamespace
from app.models import Document
from app.retrieval import event_evidence, NEWS_FRAGMENT_CHARS
from app.validation import model_grounds
import pytest
from app import agent
from app.config import settings
from app.models import Event, Run


def document(db,key,text,coverage='article'):
    d=Document(id=key,title='Новость',kind='news',publisher='Редакция',content=text,
               content_hash=key,published_at=datetime(2026,10,25),synthetic=True,
               ingestion_meta={'coverage':coverage},chunks=[{'text':text[:1000],'page':None}])
    db.add(d);db.commit();return d


def test_full_article_tail_and_exact_spans_reach_model_packet(db):
    text='Вводный контекст новости. '*300+'Важная оговорка: цены из этой новости прогнозировать нельзя.'
    d=document(db,'full-news',text)
    spans=event_evidence(db,SimpleNamespace(document_ids=[d.id],synthetic=d.synthetic))
    packet,aliases=model_grounds(spans)
    assert ''.join(e['excerpt'] for e in packet)==text
    assert packet[-1]['excerpt'].endswith('прогнозировать нельзя.')
    assert all(e['excerpt']==text[e['context_span']['start']:e['context_span']['end']] for e in spans)
    assert not any(e['context_span']['truncated'] for e in packet)
    assert len(aliases)==len(spans)


def test_large_article_is_not_limited_by_character_or_fragment_count(db):
    text='А'*(32*NEWS_FRAGMENT_CHARS)+'Конец длинной статьи.'
    d=document(db,'large-news',text)
    spans=event_evidence(db,SimpleNamespace(document_ids=[d.id],synthetic=d.synthetic))
    assert ''.join(e['excerpt'] for e in spans)==text
    assert len(spans)>32
    assert not any(e['context_span']['truncated'] for e in spans)
    assert spans[-1]['context_span']['included_characters']==len(text)


def test_full_source_precedes_contained_rss_copy(db):
    d=document(db,'article','Первый абзац. '+('Полный текст. '*400))
    rss=document(db,'rss',d.content[:100],'summary')
    spans=event_evidence(db,SimpleNamespace(document_ids=[rss.id,d.id],synthetic=d.synthetic))
    assert {e['document_id'] for e in spans}=={d.id}
    assert ''.join(e['excerpt'] for e in spans)==d.content


def test_entire_long_article_reaches_actual_synthesis_payload(client,db,monkeypatch):
    text='А'*(32*NEWS_FRAGMENT_CHARS)+'Последнее важное условие статьи.'
    doc=document(db,'generation-full-text',text)
    event=Event(title='Полный текст',document_ids=[doc.id],topics=[],published_at=doc.published_at,synthetic=True)
    db.add(event);db.commit()
    monkeypatch.setattr(settings(),'demo_mode',False)
    monkeypatch.setattr(agent,'search_documents',lambda *a,**kw:[])
    captured=[]
    class PacketCaptured(Exception):pass
    def respond(policy,payload,**kwargs):
        if 'output_schema' in payload:
            captured.append(payload);raise PacketCaptured()
        return {'topics':[],'facts':[],'tools':['event_sources','verify'],'queries':[]}
    monkeypatch.setattr(agent,'complete_json',respond)
    response=client.post('/api/analyses',json={'company_id':'demo-metal','event_id':event.id,'role':'CFO'})
    assert response.status_code==202
    with pytest.raises(PacketCaptured):agent.run_agent(db,db.get(Run,response.json()['run_id']))
    news=[e for e in captured[0]['evidence'] if e['kind']=='news']
    assert len(news)>32 and ''.join(e['excerpt'] for e in news)==text
@pytest.mark.parametrize('source', ['cbr','vedomosti'])
def test_article_parser_preserves_more_than_100000_characters(source):
    from app.ingestion import extract_article
    paragraph='Длинная публикация с подробностями события. '*2600+'Последняя фраза публикации.'
    if source=='cbr':
        html=f'<div class="landing-text"><p>{paragraph}</p></div>'
    else:
        html=f'<div class="article__body"><div class="article__boxes"><p class="box-paragraph__text">{paragraph}</p></div></div>'
    text,meta=extract_article(html.encode('utf8'),source)
    assert len(text)>100000 and text.endswith('Последняя фраза публикации.')
    assert meta['coverage']=='article'
