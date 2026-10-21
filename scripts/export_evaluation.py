"""Export real event/claim review sheets locally; never assigns expert labels."""
import argparse
import json
import sys
from pathlib import Path
from sqlalchemy import select
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
from app.db import SessionLocal, utcnow
from app.models import Company, Event, Run

parser = argparse.ArgumentParser()
parser.add_argument('--companies', nargs='+', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
with SessionLocal() as db:
    if any(db.get(Company, key) is None for key in args.companies):
        raise SystemExit('Unknown company')
    events = db.scalars(select(Event).where(Event.synthetic.is_(False)).order_by(Event.published_at.desc()).limit(50)).all()
    if len(events) < 50:
        raise SystemExit('At least 50 real events are required')
    dataset = {'status':'real-unreviewed','reviewer':None,'reviewed_at':None,'exported_at':utcnow().isoformat(),
        'companies':args.companies, 'events':[{'id':e.id, 'title':e.title,'topics':e.topics,
            'published_at':e.published_at.isoformat(), 'document_ids':e.document_ids,
            'split':'holdout' if i < 20 else 'development',
            'relevance':{f'{company}:{role}':None for company in args.companies for role in ('CEO','CFO','TREASURER')}}
            for i,e in enumerate(events)]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding='utf8')
    claims=[]
    for run in db.scalars(select(Run).where(Run.company_id.in_(args.companies),Run.status=='completed')):
        if not run.result or run.result.get('mode') != 'live':
            continue
        for section in ('facts','bank_view','impact','risks','opportunities','actions','answer'):
            for claim in run.result.get(section, []):
                claims.append({'run_id':run.id,'company_id':run.company_id,'role':run.role,'section':section,**claim,
                    'supported':None,'reviewer':None,'comment':'',
                    'evidence':[e for e in run.result['evidence'] if e['id'] in claim['evidence_ids']]})
    args.output.with_suffix('.claims.json').write_text(json.dumps({'claims':claims},ensure_ascii=False,indent=2),encoding='utf8')
print('Exported 30 development / 20 holdout events with empty labels; live claims:',len(claims))
