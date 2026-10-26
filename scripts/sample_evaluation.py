"""Deterministic, group-stratified offline sampling. Never uses ranks or relevance labels."""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.event_groups import GROUPING_VERSION, group_records
from app.news_focus import source_focus

SAMPLING_VERSION = 'editorial-sector-groups-v2'
QUOTAS = {'development':{'finance':8,'pharma':4,'industry':3,'freight':5,'trade':3,'other':7},
          'holdout':{'finance':5,'pharma':3,'industry':2,'freight':4,'trade':2,'other':4}}
PATTERNS = {
    'pharma':r'фарм|лекарств|препарат|вакцин|пневмон|грипп|риновирус|онколог',
    'industry':r'производств|промышлен|строитель|\bсталь\b|сталелит|(?:нержавеющ\w*|цен\w*|импорт\w*|экспорт\w*|рынок)(?:\s+на)?\s+стали\b|металл|рынок труда|зарплат',
    'freight':r'топлив|дизел|бензин|нефт|груз|перевоз|логист|\bпорт\b',
    'finance':r'ключев\w* став|кредит|депозит|вклад|инфляц|ликвидност|денежн\w* баз|курс\w* (?:доллар|рубл|юан)|дефолт|облигаци',
    'trade':r'экспорт|импорт|пошлин|внешнеторг|тамож|трансгранич|торгов',
}


def stratum(record):
    # Editorial subject is defined independently of company, role and ranking.
    for key, pattern in PATTERNS.items():
        if re.search(pattern,record['title'],re.I): return key
    return 'other'


def sample(corpus, context_bundle, excluded_holdout=(), seed='20261025-v3'):
    records=corpus['events']
    groups=group_records(records)
    excluded=set(excluded_holdout)|set(corpus.get('run_event_ids',[]))
    blocked={groups[i] for i in excluded if i in groups}
    # Dedup before splitting: use most complete publication as representative.
    representatives={}
    for e in records:
        group=groups[e['id']]
        old=representatives.get(group)
        quality=lambda r: (max((len(s.get('content','')) for s in r['sources']),default=0),r['published_at'],r['id'])
        if old is None or quality(e)>quality(old): representatives[group]=e
    ordered=sorted(representatives.items(),key=lambda pair:hashlib.sha256((seed+pair[0]).encode()).hexdigest())
    selected=[];used=set(); inventories={}
    for split in ('holdout','development'):
        candidates=[(g,e) for g,e in ordered if g not in used and (split!='holdout' or g not in blocked)]
        inventories[split]=dict(Counter(stratum(e) for _,e in candidates))
        for category,needed in QUOTAS[split].items():
            pool=[(g,e) for g,e in candidates if stratum(e)==category]
            # Ensure regulatory releases are not crowded out by a prolific publisher.
            pool.sort(key=lambda pair: (not any(s['publisher']=='Банк России' for s in pair[1]['sources']),
                                       hashlib.sha256((seed+split+pair[0]).encode()).hexdigest()))
            if len(pool)<needed:
                raise ValueError(f'{split}/{category}: need {needed} distinct groups, available {len(pool)}; collect sources instead of silently filling from another stratum')
            # Round-robin available publishers within each editorial stratum.
            publishers={}
            for pair in pool:publishers.setdefault(pair[1]['sources'][0]['publisher'],[]).append(pair)
            balanced=[]
            while any(publishers.values()):
                for publisher in sorted(publishers):
                    if publishers[publisher]:balanced.append(publishers[publisher].pop(0))
            for group,e in balanced[:needed]:
                used.add(group)
                selected.append({**e,'event_group':group,'split':split,'stratum':category,
                    'focus_text':source_focus(e['title'],e['sources']),
                    'relevance':{f'{c}:{r}':None for c in context_bundle['companies'] for r in ('CEO','CFO','TREASURER')},'comments':{}})
    publishers={split:dict(Counter(e['sources'][0]['publisher'] for e in selected if e['split']==split)) for split in QUOTAS}
    return {**{k:context_bundle[k] for k in ('schema_version','companies','contexts','rubric')},
        'status':'real-unreviewed','reviewer':None,'reviewer_kind':None,'reviewed_at':None,
        'exported_at':corpus['as_of'],'ranking_as_of':corpus['as_of'],'ranking_version':None,
        'events':selected,'sampling':{'version':SAMPLING_VERSION,'grouping_version':GROUPING_VERSION,
        'seed':seed,'quotas':QUOTAS,'available_groups':inventories,'publishers':publishers,
        'excluded_holdout_event_ids':sorted(excluded),'excluded_holdout_groups':sorted(blocked),
        'method':'Cross-sectional group-stratified holdout, not a future temporal sample. No ranks or relevance labels used in selection.'}}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--corpus',type=Path,required=True);p.add_argument('--context',type=Path,required=True)
    p.add_argument('--exclude-labelled',type=Path,action='append',default=[]);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists(): raise SystemExit('Output exists; labels cannot be overwritten')
    excluded={e['id'] for path in a.exclude_labelled for e in json.loads(path.read_text(encoding='utf8'))['events']}
    result=sample(json.loads(a.corpus.read_text(encoding='utf8')),json.loads(a.context.read_text(encoding='utf8')),excluded)
    with a.output.open('x',encoding='utf8') as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result['sampling']['publishers'],ensure_ascii=False))
