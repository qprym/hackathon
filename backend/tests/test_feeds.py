"""Synthetic HTML fixtures exercise the public publishers' page structure."""
from datetime import timedelta
from email.utils import format_datetime
from html import escape

import pytest
from sqlalchemy import func, select

from app import feeds, ingestion
from app.config import settings
from app.db import utcnow
from app.models import Company, Document, Event, FeedState
from app.worker import process_one

TITLE = "Проверочная новость о курсе валют и расчетах компаний"
URL = "https://www.vedomosti.ru/finance/news/2026/10/21/test-currency"
PARAGRAPHS = [
    "Учебный текст для тестирования парсера: валютные расчеты предприятий требуют сверки платежного календаря с условиями контрактов.",
    "Изменение курса валют влияет на стоимость закупок только при наличии валютных обязательств. Их размер в этом материале не указан.",
]
HTML = ("<html><header>Меню редакции</header><div class='article__body'>"
    "<button>В закладки</button><div class='article__boxes'>" +
    "".join(f"<div class='box-paragraph'><p class='box-paragraph__text'>{p}</p></div>" for p in PARAGRAPHS) +
    "<p hidden class='box-paragraph__text'>СКРЫТЫЙ ТЕКСТ</p></div>"
    "<aside>Читайте также: посторонний материал</aside></div><footer>Реклама</footer></html>").encode()


def mock_feed(monkeypatch, html=HTML, description=""):
    rss = (f"<rss><channel><item><title>{TITLE}</title><link>{URL}</link>"
        f"<pubDate>{format_datetime(utcnow())}</pubDate><description>{escape(description)}</description>"
        "</item></channel></rss>").encode()
    monkeypatch.setattr(ingestion, "safe_fetch", lambda url: rss if url == ingestion.FEEDS['vedomosti'] else html)


def test_vedomosti_paragraphs_exclude_controls_related_and_hidden():
    content, meta = ingestion.extract_article(HTML, "vedomosti")
    assert content == "\n\n".join(PARAGRAPHS)
    assert meta['coverage'] == 'article'
    assert 'box-paragraph__text' in meta['method']


def test_parser_rejects_missing_article_and_subscription():
    with pytest.raises(ValueError, match='контейнер'):
        ingestion.extract_article(b'<main>Menu</main>', 'vedomosti')
    locked = b'<script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":false}</script>' + HTML
    with pytest.raises(ValueError, match='подписке'):
        ingestion.extract_article(locked, 'vedomosti')
    with pytest.raises(ValueError, match='ограничен'):
        ingestion.extract_article(HTML + b'<div class="article-paywall">Subscribe</div>', 'vedomosti')


def test_cbr_article_adapter():
    text, meta = ingestion.extract_article(f"<nav>Menu</nav><div class='landing-text'>{PARAGRAPHS[0]}</div>".encode(), 'cbr')
    assert text == PARAGRAPHS[0] and meta['coverage'] == 'article'


def test_rss_to_real_feed_analysis_and_source(client, db, monkeypatch):
    mock_feed(monkeypatch)
    first = client.post('/api/admin/feeds/vedomosti')
    assert first.status_code == 200
    assert first.json()['articles'] == 1 and first.json()['imported'] == 1
    again = client.post('/api/admin/feeds/vedomosti').json()
    assert again['unchanged'] == 1 and again['imported'] == 0
    assert db.scalar(select(func.count()).select_from(Document).where(Document.synthetic.is_(False))) == 1
    feed = client.get('/api/feed?company_id=demo-retail&role=TREASURER').json()
    assert feed['corpus'] == 'real'
    assert not feed['items'] and feed['selection']['not_requested']==1
    feed=client.get('/api/feed',params={'company_id':'demo-retail','role':'TREASURER','q':TITLE}).json()
    assert len(feed['items']) == 1 and not feed['items'][0]['synthetic']
    event_id = feed['items'][0]['id']
    run_id = client.post('/api/analyses', json={'company_id':'demo-retail', 'event_id': event_id, 'role':'TREASURER'}).json()['run_id']
    assert process_one()
    run = client.get(f'/api/runs/{run_id}').json()
    assert run['status'] == 'completed'
    result = run['result']
    assert not result['bank_view']
    assert all(not e['synthetic'] and e['kind'] == 'news' for e in result['evidence'])
    assert any('профиль компании учебный' in s for s in result['limitations'])
    for evidence in result['evidence']:
        source = client.get('/api/sources/' + evidence['document_id']).json()
        assert evidence['excerpt'] in source['content']
        assert source['url'] == URL and source['publisher'] == 'Ведомости'
        assert source['ingestion']['coverage'] == 'article'
        assert PARAGRAPHS[1] in source['content']
    status = client.get('/api/feeds/status').json()
    vedomosti = next(s for s in status['items'] if s['key'] == 'vedomosti')
    assert vedomosti['status'] == 'ok'
    assert not status['automatic'] and not vedomosti['scheduled'] and vedomosti['next_refresh_at'] is None


def test_unavailable_article_is_labeled_summary_and_empty_is_error(client, db, monkeypatch):
    mock_feed(monkeypatch, html=b'<main>Unavailable</main>', description=PARAGRAPHS[0])
    report = ingestion.import_feed(db, 'vedomosti')
    assert report['summaries'] == 1 and report['articles'] == 0 and report['warnings']
    doc = db.scalar(select(Document).where(Document.synthetic.is_(False)))
    assert doc.ingestion_meta['coverage'] == 'summary' and doc.ingestion_meta['warning']
    mock_feed(monkeypatch, html=b'<main>Unavailable</main>')
    report = ingestion.import_feed(db, 'vedomosti')
    assert report['imported'] == 0 and len(report['errors']) == 1


def test_real_company_cannot_use_synthetic_events(client, db):
    company = db.get(Company, 'demo-metal')
    company.synthetic = False
    db.commit()
    event = db.scalar(select(Event).where(Event.synthetic.is_(True)))
    assert client.get('/api/feed?company_id=demo-metal&corpus=synthetic').status_code == 422
    assert client.post('/api/analyses', json={'company_id':company.id, 'event_id':event.id, 'role':'CFO'}).status_code == 422


def test_scheduler_due_force_and_lease_recovery(client, db, monkeypatch):
    calls = []
    def importer(db, key, on_progress):
        calls.append(key)
        on_progress()
        assert feeds.refresh_feed(key, force=True)['skipped']  # concurrent manual request cannot duplicate work
        return {'imported':1, 'articles':1, 'errors':[], 'warnings':[]}
    monkeypatch.setattr(feeds, 'import_feed', importer)
    assert feeds.refresh_feed('vedomosti')['status'] == 'ok'
    assert feeds.refresh_feed('vedomosti')['skipped']
    assert len(calls) == 1
    assert feeds.refresh_feed('vedomosti', force=True)['status'] == 'ok'
    state = db.get(FeedState, 'vedomosti')
    # An interrupted forced refresh must recover even before its old scheduled deadline.
    state.next_refresh_at = utcnow() + timedelta(hours=1)
    state.status = 'running'
    state.lease_token = 'crashed-worker'
    state.lease_until = utcnow() - timedelta(seconds=1)
    db.commit()
    assert feeds.refresh_feed('vedomosti')['status'] == 'ok'
    db.refresh(state)
    assert not state.lease_token and state.next_refresh_at > utcnow()
    assert len(calls) == 3


def test_scheduler_network_failure_is_visible_and_retried(client, db, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('network unavailable')
    monkeypatch.setattr(feeds, 'import_feed', fail)
    assert feeds.refresh_feed('cbr')['status'] == 'error'
    state = db.get(FeedState, 'cbr')
    assert state.error and state.lease_token is None
    assert 0 < (state.next_refresh_at - utcnow()).total_seconds() <= 300
    assert feeds.refresh_feed('cbr')['skipped']


def test_scheduler_runs_again_when_interval_elapses(client, monkeypatch):
    mock_feed(monkeypatch)
    now = utcnow()
    monkeypatch.setattr(feeds, 'utcnow', lambda: now)
    assert feeds.refresh_feed('vedomosti')['imported'] == 1
    now += timedelta(seconds=settings().rss_refresh_seconds + 1)
    assert feeds.refresh_feed('vedomosti')['unchanged'] == 1
