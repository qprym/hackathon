import io
from datetime import timedelta
from pypdf import PdfWriter
from sqlalchemy import func, select
from app.db import utcnow
from app.ingestion import extract_pdf, import_csv, import_document
from app.models import Company, Document, Event, Link
from app.retrieval import search_documents


def test_batch_import_crosses_boundaries_and_preserves_units(db):
    raw = ('SYNTHETIC_U;MAINOKVED_CODE;REVENUE_COMPANY;FTS_FLAG;GROUP_ID\n' +
           ''.join(f'batch-{i};25.1;1234;1.0;null\n' for i in range(620)) +
           'batch-0;25.1;7777;0;\ninvalid;25.1;bad;0;\n').encode()
    report = import_csv(db, raw, 'large.csv')
    assert report['imported'] == 620 and report['error_count'] == 2
    c = db.get(Company, 'batch-0')
    assert c.features['REVENUE_COMPANY']['value'] == 1234
    assert c.features['REVENUE_COMPANY']['unit'] == 'unknown'
    assert c.features['FTS_FLAG']['value'] is True and c.group_id is None
    import_csv(db, raw, 'large.csv')
    assert db.scalar(select(func.count()).select_from(Company)) == 620


def test_csv_rejects_extra_columns_and_bounds_errors(db):
    report = import_csv(db, ('PAYER;BENEFICIARY;PAY_AMT;PAY_CNT\n' +
        'x;y;-1;1\n'*210).encode(), 'broken.csv')
    assert report['error_count'] == 210 and len(report['errors']) == 200
    assert report['errors_truncated'] and not db.scalar(select(func.count()).select_from(Link))


def test_scanned_pdf_uses_local_ocr_and_page_provenance(monkeypatch):
    writer = PdfWriter(); writer.add_blank_page(width=600, height=800)
    buffer = io.BytesIO(); writer.write(buffer)
    body = 'Аналитический материал банка. Исторический прогноз не является актуальным обещанием. ' * 3
    seen = []
    def recognize(raw, pages):
        seen.extend(pages)
        return {1: {'text':body, 'confidence':92.5}}
    monkeypatch.setattr('app.ocr.recognize_pages', recognize)
    content, chunks = extract_pdf(buffer.getvalue())
    assert seen == [1] and body.strip() in content
    assert chunks[0]['page'] == 1 and chunks[0]['extraction'] == 'ocr'
    assert chunks[0]['confidence'] == 92.5


def test_low_confidence_ocr_not_used_as_evidence(db):
    import_document(db, title='Ключевая ставка и кредиты', content='Ключевая ставка и условия кредита. ' * 10,
        kind='bank', publisher='Тест', published_at=utcnow(),
        chunks=[{'text':'Ключевая ставка кредит', 'page':1,'extraction':'ocr','confidence':40}])
    assert search_documents(db, 'ключевая ставка кредит', kind='bank') == []


def test_search_finds_event_beyond_feed_top_fifty(client, db):
    for i in range(70):
        db.add(Event(title=f'Кредитные ставки проверка {i}', document_ids=[], topics=['rates'], published_at=utcnow(), synthetic=True))
    target = Event(title='Редкая проверочная новость об искусстве', document_ids=[], topics=[],
                   published_at=utcnow()-timedelta(days=1), synthetic=True)
    db.add(target); db.commit()
    feed = client.get('/api/feed?company_id=demo-metal&corpus=synthetic').json()['items']
    assert target.id not in {e['id'] for e in feed}
    found = client.get('/api/feed?company_id=demo-metal&corpus=synthetic&q=Редкая').json()['items']
    assert [e['id'] for e in found] == [target.id]


def test_bank_library_is_dated_and_exposes_source_lookup(client):
    library = client.get('/api/library')
    assert library.status_code == 200 and library.json()
    for item in library.json():
        source = client.get('/api/sources/' + item['id']).json()
        assert source['kind'] == 'bank' and source['published_at'] == item['published_at']
    client.post('/api/auth/logout')
    assert client.get('/api/library').status_code == 401


def test_bank_position_requires_application_or_explicit_limit():
    from app.agent import validate_insight
    from app.schemas import Claim, Insight
    evidence = [{'id':'bank','kind':'bank','excerpt':'Банк ожидает охлаждение спроса.'}]
    insight = Insight(headline='Спрос', bank_view=[Claim(text=evidence[0]['excerpt'], evidence_ids=['bank'])],
                      impact=[Claim(text='Влияние следует проверить.', assumption=True)])
    assert any('не связана' in message for message in validate_insight(insight,evidence,{'features':{}}))
    insight.impact[0].evidence_ids = ['bank']
    assert not validate_insight(insight,evidence,{'features':{}})
