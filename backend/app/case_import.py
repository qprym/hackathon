"""Offline case loader: python -m app.case_import /case --csv / --ocr / --bank."""
import argparse
import hashlib
import io
import json
import time
from datetime import datetime
from pathlib import Path
from pypdf import PdfReader
from sqlalchemy import select
from .db import SessionLocal, utcnow
from .ingestion import extract_pdf, import_csv, import_document, pdf_chunks
from .models import Audit, Company, Document, User


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--csv', action='store_true')
    parser.add_argument('--ocr', action='store_true')
    parser.add_argument('--bank', action='store_true')
    parser.add_argument('--grant', nargs='*', default=[])
    parser.add_argument('--username', default='demo')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    root = args.directory.resolve()
    report_path = root / 'import-report.json'
    report = json.loads(report_path.read_text(encoding='utf8')) if report_path.exists() else {}
    with SessionLocal() as db:
        if args.csv:
            for filename in ('df_Uid_data_hack.csv', 'df_Uid_payment_hack.csv', 'df_Fid_Uid_link_hack.csv'):
                raw = (root / filename).read_bytes()
                sha = hashlib.sha256(raw).hexdigest()
                previous = db.scalars(select(Audit).where(Audit.action == 'case_csv_import')).all()
                if not args.force and any(a.details.get('sha256') == sha for a in previous):
                    print(json.dumps({'file': filename, 'status': 'already_imported'}), flush=True)
                    continue
                started = time.monotonic()
                result = import_csv(db, raw, filename)
                result.pop('company_ids')
                result.update(sha256=sha, seconds=round(time.monotonic()-started, 2))
                report[filename] = result
                db.add(Audit(action='case_csv_import', actor='local-import', details={'file':filename, **result}))
                db.commit()
                saved_report = json.loads(report_path.read_text(encoding='utf8')) if report_path.exists() else {}
                saved_report[filename] = result
                report_path.write_text(json.dumps(saved_report, ensure_ascii=False, indent=2), encoding='utf8')
                print(json.dumps({'file': filename, **result}, ensure_ascii=True), flush=True)
        if args.ocr:
            for path in sorted(root.glob('*.pdf')):
                target = path.with_suffix('.ocr.json')
                raw = path.read_bytes()
                sha = hashlib.sha256(raw).hexdigest()
                if target.exists() and json.loads(target.read_text(encoding='utf8')).get('sha256') == sha:
                    continue
                content, chunks, pages = extract_pdf(raw, with_pages=True)
                target.write_text(json.dumps({'sha256':sha,'content':content,'chunks':chunks,'pages':pages}, ensure_ascii=False), encoding='utf8')
                print(json.dumps({'file':path.name,'characters':len(content),'pages':len(set(c['page'] for c in chunks))}, ensure_ascii=True), flush=True)
        if args.bank:
            # Dates and titles are reviewed against PDF pages, never inferred from modification times.
            manifest = json.loads((root / 'bank-manifest.json').read_text(encoding='utf8'))
            for item in manifest:
                path = root / Path(item['filename']).name
                raw = path.read_bytes()
                saved = json.loads(path.with_suffix('.ocr.json').read_text(encoding='utf8'))
                sha = hashlib.sha256(raw).hexdigest()
                if sha != saved['sha256']:
                    raise ValueError('OCR does not match original PDF')
                # Rebuild paragraph chunks from the cached full OCR page text.
                # Full content joins pages with a single newline, so preserve each page separately on extraction.
                if 'pages' in saved:
                    saved['chunks'] = [{**chunk,'extraction':'ocr','confidence':page['confidence']}
                        for page in saved['pages'] for chunk in pdf_chunks(page['text'], page['number'])]
                original = sha + '.pdf'
                Path('uploads').mkdir(exist_ok=True)
                Path('uploads', original).write_bytes(raw)
                existing = db.scalar(select(Document).where(Document.ingestion_meta['original_file'].as_string() == original))
                effective_date = datetime.fromisoformat(item['date']) if item.get('date') else existing.published_at if existing else utcnow()
                doc, created = import_document(db, title=item['title'], content=saved['content'], chunks=saved['chunks'],
                    kind='bank', publisher='Альфа-Банк · материалы кейса', published_at=effective_date,
                    url=item['url'], ingestion_meta={'coverage':'provided','extraction':'ocr','original_file':original,
                    'source_filename':path.name,'date_source':item['date_source'], 'date_kind':item.get('date_kind','publication'),
                    'page_count':len(PdfReader(io.BytesIO(raw)).pages),
                    'warning':'Распознано локальным OCR. Числа, таблицы и графики сверяйте с PDF; историческая оценка банка относится к дате материала.'})
                report[path.name] = {'document_id':doc.id, 'created':created, 'sha256':sha, 'pages':len(set(c['page'] for c in saved['chunks']))}
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        if args.grant:
            user = db.scalar(select(User).where(User.username == args.username))
            if not user or any(db.get(Company, key) is None for key in args.grant):
                raise ValueError('Unknown user or company')
            user.company_ids = sorted(set(user.company_ids + args.grant))
            db.add(Audit(action='case_access',actor=user.id,details={'company_ids':args.grant}))
            db.commit()


if __name__ == '__main__':
    main()
