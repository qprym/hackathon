"""Freeze 30 development events and 20 unseen event groups; no model/network calls."""
import argparse, hashlib, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.event_groups import group_records


def build(corpus,baseline,ids):
    index={e['id']:e for e in corpus['events']}
    union={**index,**{e['id']:e for e in baseline['events']}}
    groups=group_records(list(union.values()))
    known={groups[e['id']] for e in baseline['events']}
    urls={s.get('url') for e in baseline['events'] for s in e['sources'] if s.get('url')}
    if len(ids)!=20 or len(set(ids))!=20:raise ValueError('Exactly 20 distinct holdout events required')
    selected=[];seen=set()
    for key in ids:
        e=index[key];group=groups[key]
        if group in known or group in seen or any(s.get('url') in urls for s in e['sources']):
            raise ValueError('Holdout overlaps known event groups or sources: '+e['title'])
        seen.add(group)
        selected.append({**e,'event_group':group,'split':'holdout',
            'relevance':{f'{c}:{r}':None for c in baseline['companies'] for r in ('CEO','CFO','TREASURER')},'comments':{}})
    dev=[{**e,'event_group':groups[e['id']]} for e in baseline['events'] if e['split']=='development']
    if len(dev)<30:raise ValueError('Need at least 30 development events')
    return {**baseline,'events':dev+selected,'status':'real-unreviewed','reviewer_kind':'ai','independent':False,
        'reviewed_at':None,'ranking_version':None,'exported_at':'2026-10-26T12:00:00+03:00',
        'sampling':{'method':'Fixed development; manually selected unseen groups by subject before labelling; cross-sectional, not temporal or independent.',
                    'development':len(dev),'holdout':len(selected),'excluded_previous_groups':len(known)},
        'known_limitations':['AI-разметка не является независимой оценкой.','Новый holdout не является будущей временной выборкой.',
                            'Достижимый P@5 определяется наличием релевантных событий для каждой роли.']}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('corpus','baseline','holdout-ids','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    result=build(json.loads(a.corpus.read_text(encoding='utf8')),json.loads(a.baseline.read_text(encoding='utf8')),
                 json.loads(a.holdout_ids.read_text(encoding='utf8')))
    result['input_sha256']={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in (a.corpus,a.baseline,a.holdout_ids)}
    with a.output.open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(result['sampling'])
