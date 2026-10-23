"""Replay local corpus and saved runs without HTTP, a provider key, or live DB writes.

This is a regression audit, not an independently labelled relevance benchmark.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['DEMO_MODE'] = 'true'
os.environ['LLM_API_KEY'] = 'offline-unused'

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.bank_relevance import SEARCH_VERSION, subject_match
from app.db import Base
from app.models import Document, Event
from app.retrieval import classify, rank_event, search_documents
from app.schemas import Insight
from app.validation import validate_insight


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def audit(corpus, records, profiles=None):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    report = {'search_version': SEARCH_VERSION, 'llm_calls': 0,
              'scope': 'Local regression replay, not independent quality metrics', 'runs': []}
    with Session(engine) as db:
        for doc in corpus['documents']:
            db.add(Document(id=doc['id'], title=doc['title'], content=doc['content'], kind=doc['kind'],
                publisher=doc['publisher'], url=doc['url'], synthetic=doc['synthetic'],
                published_at=datetime.fromisoformat(doc['published_at'].rstrip('Z')),
                content_hash=hashlib.sha256(doc['content'].encode()).hexdigest(),
                chunks=doc['chunks'], ingestion_meta=doc.get('ingestion', {})))
        db.commit()
        for record in records:
            run = record['run']
            result = run['result']
            title = run.get('event_title') or result['headline']
            news = [e for e in result['evidence'] if e['kind'] == 'news']
            cutoff = max(datetime.fromisoformat(e['published_at'].rstrip('Z')) for e in news)
            found = search_documents(db, title, kind='bank', before=cutoff, focus=title)
            before = {e['document_id']: e['title'] for e in result['evidence'] if e['kind'] == 'bank'}
            annotated = [{**e, **({'relevance': relation} if relation else {})}
                         for e in result['evidence']
                         for relation in [subject_match(title, e['excerpt']) if e['kind'] == 'bank' else None]]
            insight = Insight.model_validate({key: value for key, value in result.items() if key in Insight.model_fields})
            issues = validate_insight(insight, annotated, {'features': result['context_features']},
                                      event_source_ids={e['id'] for e in news})
            entry = {'run_id':run['id'], 'event':title, 'bank_documents_before':before,
                     'selection_after':found, 'saved_draft_issues_under_current_rules':issues}
            if profiles:
                # Same event, same evidence and timestamp: only company and role vary.
                event = Event(title=title, topics=classify(title + ' ' + ' '.join(e['excerpt'] for e in news)),
                              published_at=cutoff, document_ids=list({e['document_id'] for e in news}))
                entry['same_event_rankings'] = {company: {role:rank_event(event, profiles[company], role)
                    for role in ('CEO','CFO','TREASURER')} for company in ('U_6923','U_26491','U_11656') if company in profiles}
            report['runs'].append(entry)
    engine.dispose()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--run', type=Path, action='append', required=True)
    parser.add_argument('--profiles', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(read(args.corpus), [read(path) for path in args.run],
                   read(args.profiles)['contexts'] if args.profiles else None)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps({'llm_calls':0, 'runs':[{k:v for k,v in run.items() if k not in ('selection_after','same_event_rankings')}
        | {'selection_after':[{'title':e['title'],'page':e['page'],'relevance':e['relevance']} for e in run['selection_after']]}
        for run in report['runs']]}, ensure_ascii=False, indent=2))
