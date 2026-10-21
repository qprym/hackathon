import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
from app.context import company_context
from app.db import SessionLocal, utcnow
from app.models import Company, Event
from app.retrieval import rank_event

parser = argparse.ArgumentParser()
parser.add_argument('--split', choices=['development', 'holdout'], default='holdout')
parser.add_argument('--data', type=Path, default=root / 'data/evaluation/events.json')
args = parser.parse_args()
dataset = json.loads(args.data.read_text(encoding='utf-8'))
records = [e for e in dataset['events'] if e['split'] == args.split]
missing = sum(v is None for r in records for v in r['relevance'].values())
if missing or not dataset.get('reviewer') or not dataset.get('reviewed_at'):
    print(json.dumps({'status': 'incomplete', 'split': args.split, 'events':len(records), 'missing_labels':missing,
        'message':'Independent human labels and reviewer metadata are required. No quality score is asserted.'}, indent=2))
    raise SystemExit(2)
results = {}
with SessionLocal() as db:
    for company_id in dataset.get('companies', ['demo-metal','demo-retail','demo-logistics']):
        company = db.get(Company,company_id)
        if company is None:
            raise SystemExit('Seed the demo database before evaluating. Set DATABASE_URL to the intended instance.')
        context = company_context(db,company)
        for role in ['CEO','CFO','TREASURER']:
            key = f'{company_id}:{role}'
            ordered = sorted(records,key=lambda r:rank_event(Event(title=r['title'],topics=r['topics'],published_at=datetime.fromisoformat(r['published_at'].rstrip('Z')) if r.get('published_at') else utcnow(),document_ids=r.get('document_ids', [])),context,role)['score'],reverse=True)
            top = ordered[:5]
            if any(r['relevance'][key] not in [0,1,2] for r in ordered):
                raise SystemExit('Relevance labels must be 0, 1 or 2.')
            results[key] = sum(r['relevance'][key] >= 1 for r in top)/len(top)
print(json.dumps({'split':args.split,'precision_at_5':results,'macro_average':sum(results.values())/len(results),
    'synthetic_scaffold':dataset.get('status','').startswith('synthetic'),'reviewer':dataset['reviewer']},indent=2))
