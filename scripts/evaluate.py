"""Score labelled snapshots without confusing AI review with independent acceptance."""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
from app.retrieval import RANKING_VERSION, rank_event
from app.news_focus import source_focus
from app.semantic_ranking import fingerprint
from app.feed_selection import assemble_feed, ORDERING_VERSION

ROLES = ('CEO','CFO','TREASURER')


def timestamp(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def evaluate(dataset, split, *, ranker=rank_event, ranking_version=RANKING_VERSION, arranger=None):
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
    scores, top_ids, ceilings, served, shown_precision = {}, {}, {}, {}, {}
    for company_id in companies:
        for role in ROLES:
            key = f'{company_id}:{role}'
            def ranked(record):
                date = timestamp(record['published_at'])
                event = SimpleNamespace(id=record['id'],title=record['title'],topics=record['topics'],published_at=date,
                                        focus_text=source_focus(record['title'],record.get('sources',[])))
                result=ranker(event, dataset['contexts'][company_id], role, as_of=as_of)
                return result, date
            ranked_records=[(r,*ranked(r)) for r in records]
            ranked_records.sort(key=lambda item:(item[1]['score'],item[2],item[0]['id']),reverse=True)
            if arranger:
                # Pass only serving metadata and model outputs, never labels/comments/strata.
                entries=[{'id':r['id'],'title':r['title'],'published_at':r['published_at'],
                    'event_group':r.get('event_group',r['id']),
                    'publisher':r.get('sources',[{}])[0].get('publisher',''),
                    'document_id':r.get('sources',[{}])[0].get('id'),**result}
                    for r,result,_ in ranked_records if result.get('eligible',True)]
                by_id={r['id']:(r,result,date) for r,result,date in ranked_records}
                ranked_records=[by_id[e['id']] for e in arranger(entries,role=role)]
            top=[];seen=set()
            for record,result,_ in ranked_records:
                group=record.get('event_group',record['id'])
                if not result.get('eligible',True) or group in seen:continue
                top.append(record);seen.add(group)
                if len(top)==5:break
            scores[key] = sum(r['relevance'][key] >= 1 for r in top)/5
            top_ids[key] = [r['id'] for r in top]
            served[key]=len(top)
            shown_precision[key]=sum(r['relevance'][key]>=1 for r in top)/len(top) if top else None
            ceilings[key] = min(5, len({r.get('event_group',r['id']) for r in records if r['relevance'][key]>=1}))/5
    kind = dataset.get('reviewer_kind', 'human')
    independent = kind == 'human' and dataset.get('independent', True) is True
    groups = {}
    for event in dataset['events']:
        groups.setdefault(event.get('event_group', event['id']), set()).add(event['split'])
    overlap = sorted(group for group, splits in groups.items() if len(splits) > 1)
    eligible = independent and not overlap
    return {'status':'ai_reviewed' if kind == 'ai' else 'reviewed','split':split,
        'reviewer_kind':kind,'independent':independent,'acceptance_eligible':eligible,
        'cross_split_event_groups':overlap, 'precision_at_5':scores,'macro_average':sum(scores.values())/len(scores),
        'precision_at_5_ceiling':ceilings, 'returned_at_5':served,'precision_of_returned':shown_precision,
        'target_met':all(v >= .8 for v in scores.values()) if eligible else None, 'top_event_ids':top_ids,
        'ranking_version':ranking_version,'exported_ranking_version':dataset.get('ranking_version'),
        'ranking_as_of':dataset['ranking_as_of'],'reviewer':dataset['reviewer'],
        'synthetic_scaffold':dataset.get('status','').startswith('synthetic')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--split', choices=['development','holdout'], default='holdout')
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--predictions',type=Path,help='Saved, reviewed provider predictions; never calls a model')
    parser.add_argument('--ordering',choices=['balanced','model_score'],default='model_score',help='balanced is an offline diversity experiment, not live listwise selection')
    args = parser.parse_args()
    dataset=json.loads(args.data.read_text(encoding='utf8'))
    result = (evaluate_predictions(dataset,json.loads(args.predictions.read_text(encoding='utf8')),args.split,ordering=args.ordering)
              if args.predictions else evaluate(dataset,args.split))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['status'] in ('reviewed', 'ai_reviewed') else 2)


def evaluate_predictions(dataset,predictions,split,*,ordering='model_score'):
    if ordering not in ('balanced','model_score'):raise ValueError('Unknown ordering mode')
    missing=[]
    for company in dataset['companies']:
        if predictions.get('context_fingerprints',{}).get(company)!=fingerprint(dataset['contexts'][company]):
            return {'status':'incomplete','message':'Company context differs from the labelled snapshot','company':company}
        for event in dataset['events']:
            if event['split']!=split:continue
            row=predictions.get('predictions',{}).get(company,{}).get(event['id'],{})
            if row.get('status')!='completed' or (row.get('result') or {}).get('review',{}).get('version')!=predictions.get('review_version'):
                missing.append({'company':company,'event_id':event['id'],'status':row.get('status','missing')})
    if missing:return {'status':'incomplete','message':'Provider predictions are missing or not verified','missing_predictions':missing}
    def ranker(event,context,role,**kwargs):
        result=predictions['predictions'][context['id']][event.id]['result'];grade=result['roles'][role]
        return {'score':grade['score'],'eligible':grade['relevance']>0,'topics':result.get('topics',[]),
                'exposure':{'level':{0:'unknown',1:'indirect',2:'direct'}[grade['relevance']]}}
    result=evaluate(dataset,split,ranker=ranker,ranking_version=predictions['selection_version']+'/'+predictions['review_version'],
                    arranger=assemble_feed if ordering=='balanced' else None)
    result['ordering_version']=ORDERING_VERSION if ordering=='balanced' else 'model_score'
    result['model_id']=predictions['model_id'];result['prediction_source']='saved_provider_responses'
    return result


if __name__ == '__main__':
    main()
