"""Export a private, reproducible human review bundle. Never assigns labels."""
import argparse
import json
import sys
from pathlib import Path
from sqlalchemy import select

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
sys.path.insert(0, str(root / 'scripts'))
from sample_evaluation import sample
from app.context import company_context
from app.db import SessionLocal, utcnow
from app.models import Company, Document, Event, Run
from app.retrieval import RANKING_VERSION
from app.cashflow import VALIDATION_VERSION
from app.bank_relevance import SEARCH_VERSION

ROLES = ('CEO', 'CFO', 'TREASURER')


def build_bundle(db, company_ids, excluded_ids=(), *, as_of=None):
    if len(set(company_ids)) != 3:
        raise ValueError('Exactly three distinct companies are required')
    companies = [db.get(Company, key) for key in company_ids]
    if any(c is None or c.synthetic for c in companies):
        raise ValueError('Three real case companies are required')
    as_of = as_of or utcnow()
    contexts = {c.id: company_context(db, c, company_ids) for c in companies}
    used = set(db.scalars(select(Run.event_id)).all()) | set(excluded_ids)
    events = db.scalars(select(Event).where(Event.synthetic.is_(False), Event.published_at <= as_of,
        ).order_by(Event.published_at.desc(), Event.id).limit(500)).all()
    selected = []
    for event in events:
        documents = db.scalars(select(Document).where(Document.id.in_(event.document_ids),
                                                     Document.synthetic.is_(False))).all()
        if not documents:
            continue
        selected.append({'id': event.id, 'title': event.title, 'topics': event.topics,
            'published_at': event.published_at.isoformat(), 'document_ids': event.document_ids,
            'split': 'holdout' if len(selected) < 20 else 'development',
            'sources': [{'id':d.id,'title':d.title,'publisher':d.publisher,'url':d.url,
                         'published_at':d.published_at.isoformat(),'content':d.content,
                         'coverage':(d.ingestion_meta or {}).get('coverage', 'unknown')} for d in documents],
            'relevance': {f'{key}:{role}': None for key in company_ids for role in ROLES},
            'comments': {}})
    dataset = {'schema_version': 2, 'status': 'real-unreviewed', 'reviewer': None, 'reviewed_at': None,
        'exported_at': as_of.isoformat(), 'ranking_as_of': as_of.isoformat(), 'ranking_version': RANKING_VERSION,
        'companies': company_ids, 'contexts': contexts, 'events': selected,
        'rubric': {'0':'Нет применимой связи с компанией и ролью','1':'Косвенная, но полезная связь',
                   '2':'Приоритетная новость с конкретным механизмом влияния'},
        'instructions': 'Оценивайте по источнику и профилю, не по порядку ленты. Сначала development; holdout после фиксации ранжирования. Пустая оценка — недостаточно данных, не ноль.'}
    dataset = sample({'as_of':as_of.isoformat(),'events':selected,'run_event_ids':sorted(used)},dataset,used)
    dataset['ranking_version'] = RANKING_VERSION
    claims, seen_profiles = [], set()
    for run in db.scalars(select(Run).where(Run.company_id.in_(company_ids), Run.status=='completed')
                         .order_by(Run.created_at.desc(), Run.id)):
        result = run.result or {}
        key = (run.company_id, run.role)
        if result.get('mode') != 'live' or result.get('verification') != 'checked' or key in seen_profiles:
            continue
        seen_profiles.add(key)
        for section in ('facts','bank_view','impact','risks','opportunities','actions','answer'):
            for index, claim in enumerate(result.get(section, [])):
                claims.append({'id':f'{run.id}:{section}.{index}', 'run_id':run.id,'company_id':run.company_id,
                    'role':run.role, 'section':section, **claim, 'supported':None,'reviewer':None,'comment':'',
                    'context_features':result.get('context_features', {}),
                    'validation_version':result.get('validation_version'), 'search_version':result.get('search_version'),
                    'outdated':result.get('validation_version') != VALIDATION_VERSION or result.get('search_version') != SEARCH_VERSION,
                    'evidence':[e for e in result.get('evidence', []) if e['id'] in claim['evidence_ids']]})
    claimset = {'schema_version':2, 'kind':'claims', 'reviewer':None, 'reviewed_at':None,
        'exported_at':as_of.isoformat(), 'scope':'Latest published checked live analysis per available company and role; historical versions marked separately',
        'claims':claims}
    return dataset, claimset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--companies', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exclude', type=Path, action='append', default=[])
    args = parser.parse_args()
    outputs = [args.output, args.output.with_suffix('.claims.json')]
    if any(path.exists() for path in outputs):
        raise SystemExit('Output already exists. Choose a new name; existing labels will not be overwritten.')
    excluded = {e['id'] for path in args.exclude for e in json.loads(path.read_text(encoding='utf8'))['events']}
    with SessionLocal() as db:
        bundles = build_bundle(db, args.companies, excluded)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for path, data in zip(outputs, bundles):
        with path.open('x', encoding='utf8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, default=str)
    print('Exported 30 development / 20 untouched holdout events, 450 empty labels; published live claims:', len(bundles[1]['claims']))


if __name__ == '__main__':
    main()
