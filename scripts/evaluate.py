"""Score human labels using immutable profile/time snapshots; no API calls."""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
from app.retrieval import RANKING_VERSION, rank_event

ROLES = ('CEO','CFO','TREASURER')


def timestamp(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def evaluate(dataset, split):
    records = [e for e in dataset['events'] if e['split'] == split]
    companies = dataset['companies']
    keys = [f'{c}:{r}' for c in companies for r in ROLES]
    missing = sum(type(e.get('relevance',{}).get(key)) is not int or e['relevance'][key] not in (0,1,2)
                  for e in records for key in keys)
    required = 20 if split == 'holdout' else 30
    if (len(records) != required or len({e['id'] for e in dataset['events']}) != len(dataset['events'])
            or len(set(companies)) != 3 or missing or not dataset.get('reviewer') or not dataset.get('reviewed_at')):
        return {'status':'incomplete','split':split,'events':len(records),'missing_labels':missing,
                'message':'Need three companies, complete independent labels, reviewer/date and 30/20 distinct events; no score asserted.'}
    if not dataset.get('ranking_as_of') or any(c not in dataset.get('contexts',{}) for c in companies):
        return {'status':'incomplete','message':'Export a snapshot bundle: contexts and ranking_as_of are required.'}
    as_of = timestamp(dataset['ranking_as_of'])
    scores, top_ids = {}, {}
    for company_id in companies:
        for role in ROLES:
            key = f'{company_id}:{role}'
            def order(record):
                date = timestamp(record['published_at'])
                event = SimpleNamespace(title=record['title'],topics=record['topics'],published_at=date)
                return rank_event(event, dataset['contexts'][company_id], role, as_of=as_of)['score'], date, record['id']
            top = sorted(records,key=order,reverse=True)[:5]
            scores[key] = sum(r['relevance'][key] >= 1 for r in top)/5
            top_ids[key] = [r['id'] for r in top]
    return {'status':'reviewed','split':split,'precision_at_5':scores,'macro_average':sum(scores.values())/len(scores),
        'target_met':all(v >= .8 for v in scores.values()), 'top_event_ids':top_ids,
        'ranking_version':RANKING_VERSION,'exported_ranking_version':dataset.get('ranking_version'),
        'ranking_as_of':dataset['ranking_as_of'],'reviewer':dataset['reviewer'],
        'synthetic_scaffold':dataset.get('status','').startswith('synthetic')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--split', choices=['development','holdout'], default='holdout')
    parser.add_argument('--data', type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(json.loads(args.data.read_text(encoding='utf8')), args.split)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['status']=='reviewed' else 2)


if __name__ == '__main__':
    main()
