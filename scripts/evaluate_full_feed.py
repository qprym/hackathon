"""Score complete checked feed jobs against a frozen cohort; never calls a model."""
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.full_selection import VERSION, validate
from app.semantic_ranking import ROLES, fingerprint


def metrics(records, ordered_ids, key, draft_positive=()):
    index={e['id']:e for e in records}
    if any(type(e['relevance'].get(key)) is not int for e in records):raise ValueError('Incomplete labels')
    ids=[k for k in ordered_ids if k in index]
    group=lambda k:index[k].get('event_group',k)
    positive={group(k) for k,e in index.items() if e['relevance'][key]>0}
    selected={group(k) for k in ids if index[k]['relevance'][key]>0}
    top=ids[:5]; relevant=len({group(k) for k in top if index[k]['relevance'][key]>0})
    return {'events':len(records),'positive_event_groups':len(positive),'returned':len(ids),
        'precision_at_5':relevant/5,'precision_at_5_ceiling':min(5,len(positive))/5,
        'precision_of_returned_at_5':relevant/len(top) if top else None,
        'recall':len(selected)/len(positive) if positive else None,
        'duplicate_cards':len(ids)-len({group(k) for k in ids}),
        'missed_positive_groups':len(positive-selected),
        'review_false_rejections_on_ai_labels':len({group(k) for k in draft_positive if k in index
            and index[k]['relevance'][key]>0 and group(k) not in selected}),
        'top_event_ids':top}


def evaluate(dataset,jobs,split='holdout'):
    records=[e for e in dataset['events'] if e['split']==split]
    roles={};missing=[];latencies={}
    urls={s['url']:e['id'] for e in records for s in e['sources'] if s.get('url')}
    ids={e['id'] for e in records}
    for company in dataset['companies']:
        candidates=[j for j in jobs if j.get('company_id')==company and j.get('status')=='completed'
                    and (j.get('response') or {}).get('version')==VERSION
                    and j['response'].get('verification')=='checked']
        candidates.sort(key=lambda j:j.get('created_at',''),reverse=True)
        job=candidates[0] if candidates else None
        if not job:
            missing.extend(f'{company}:{r}' for r in ROLES);continue
        payload=job['payload'];result=job['response']
        if fingerprint(payload['context'])!=fingerprint(dataset['contexts'][company]):
            raise ValueError('Context changed: '+company)
        parsed=validate({'decisions':result['decisions'],'order':result['order']},payload)
        mapping={}
        for article in payload['articles']:
            matches={article['event_id']} & ids
            matches.update(urls[d['url']] for d in article['documents'] if d.get('url') in urls)
            if len(matches)>1:raise ValueError('Article spans multiple labelled events')
            if matches:mapping[article['article_id']]=next(iter(matches))
        if set(mapping.values())!=ids:raise ValueError('The job did not assess all events in this cohort')
        groups={a['article_id']:a['article_id'] for a in payload['articles']}
        def root(k):
            while groups[k]!=k:k=groups[k]
            return k
        for a,b in result.get('duplicate_pairs',[]):groups[root(a)]=root(b)
        for role in ROLES:
            order=[];seen=set()
            for alias in getattr(parsed.order,role):
                group=root(alias)
                if group in seen:continue
                seen.add(group)
                if alias in mapping:order.append(mapping[alias])
            draft=set()
            for step in result.get('steps',[]):
                if step['step']=='classify_and_order':
                    draft.update(mapping[d['article_id']] for d in step['response']['decisions']
                        if d['article_id'] in mapping and d[role]['decision'] in ('direct','scenario'))
            key=f'{company}:{role}';roles[key]=metrics(records,order,key,draft)
        if job.get('created_at') and job.get('finished_at'):
            latencies[company]=(datetime.fromisoformat(job['finished_at'])-datetime.fromisoformat(job['created_at'])).total_seconds()
    ceilings={f'{c}:{r}':min(5,len({e.get('event_group',e['id']) for e in records
        if e['relevance'][f'{c}:{r}']>0}))/5 for c in dataset['companies'] for r in ROLES}
    overlap={}
    for e in dataset['events']:overlap.setdefault(e.get('event_group',e['id']),set()).add(e['split'])
    if any(len(s)>1 for s in overlap.values()):raise ValueError('Development/holdout event groups overlap')
    return {'status':'not_run' if not roles else 'partial' if missing else 'scored',
        'version':VERSION,'split':split,'events':len(records),'roles':roles,'missing_roles':missing,
        'precision_at_5_ceiling':ceilings,'job_latency_seconds':latencies,
        'reviewer_kind':dataset.get('reviewer_kind'),'independent':False,'acceptance_eligible':False,
        'target_met':None,'note':'AI labels; quality of an absent model response is not inferred from code tests.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True)
    p.add_argument('--responses',type=Path);p.add_argument('--split',choices=['development','holdout'],default='holdout')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    data=json.loads(a.data.read_text(encoding='utf8'));jobs=json.loads(a.responses.read_text(encoding='utf8')) if a.responses else []
    result=evaluate(data,jobs,a.split)
    result['input_sha256']={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in [a.data,a.responses] if path}
    with a.output.open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k not in ('roles','input_sha256')},ensure_ascii=False))
