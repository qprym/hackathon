"""Compare reading-list assembly on immutable provider responses, without HTTP."""
import argparse
import hashlib
import json
from pathlib import Path
from evaluate import evaluate_predictions, ROLES
from app.event_groups import diversified
from app.feed_selection import assemble_feed, ORDERING_VERSION


def replay(dataset, predictions):
    splits = {}
    for split in ('development', 'holdout'):
        splits[split] = {mode: evaluate_predictions(dataset, predictions, split, ordering=mode)
                         for mode in ('model_score', 'balanced')}
        if any(r['status'] == 'incomplete' for r in splits[split].values()):
            raise ValueError('Predictions/context/labels incomplete; replay refused')
    index = {e['id']: e for e in dataset['events']}
    full = {}
    for company in dataset['companies']:
        for role in ROLES:
            key = f'{company}:{role}'
            entries = []
            for event in dataset['events']:
                result = predictions['predictions'][company][event['id']]['result']
                grade = result['roles'][role]
                if not grade['relevance']:
                    continue
                # No labels, editorial strata, comments or company ID reach assembly.
                entries.append({'id':event['id'], 'title':event['title'], 'published_at':event['published_at'],
                    'event_group':event.get('event_group',event['id']), 'publisher':event['sources'][0]['publisher'],
                    'document_id':event['sources'][0].get('id'), 'score':grade['score'], 'eligible':True,
                    'topics':result['topics'], 'exposure':{'level':'direct' if grade['relevance']==2 else 'indirect'}})
            before = diversified(sorted(entries, key=lambda r:(r['score'],r['published_at'],r['id']), reverse=True))
            after = assemble_feed(entries, role=role)
            def summary(rows):
                top = rows[:5]
                return {'precision_at_5':sum(index[r['id']]['relevance'][key]>0 for r in top)/5,
                        'rate_topic_cards':sum('rates' in r['topics'] for r in top),
                        'top_5':top, 'returned_count':len(rows)}
            full[key] = {'before':summary(before), 'after':summary(after)}
    return {'ordering_version':ORDERING_VERSION, 'method':'Offline replay of saved model scores; no model calls',
            'independent':False, 'acceptance_eligible':False, 'target_met':None,
            'warning':'Previously inspected AI-labelled data. Changes to list policy were informed by this set. No blind acceptance claim.',
            'splits':splits, 'full_feed':full,
            'full_feed_mean':{phase:sum(v[phase]['precision_at_5'] for v in full.values())/len(full) for phase in ('before','after')}}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True)
    p.add_argument('--predictions',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise SystemExit('Choose a new output path; preserve previous reports')
    contents={name:path.read_bytes() for name,path in [('dataset',a.data),('predictions',a.predictions)]}
    result=replay(json.loads(contents['dataset']),json.loads(contents['predictions']))
    result['input_sha256']={name:hashlib.sha256(raw).hexdigest() for name,raw in contents.items()}
    with a.output.open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'full_feed_mean':result['full_feed_mean'],
        'splits':{split:{mode:r['macro_average'] for mode,r in values.items()} for split,values in result['splits'].items()}},ensure_ascii=False))
