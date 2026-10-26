"""Score saved listwise responses against frozen labels; never calls a provider."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.reading_list import validate,VERSION
from app.semantic_ranking import ROLES


def main():
    p=argparse.ArgumentParser()
    for field in ('data','mapping','before','output'):p.add_argument('--'+field,type=Path,required=True)
    p.add_argument('--reports',nargs='+',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise SystemExit('Choose a new output path')
    dataset=json.loads(a.data.read_text(encoding='utf8'));mapping=json.loads(a.mapping.read_text(encoding='utf8'))['mapping']
    baseline=json.loads(a.before.read_text(encoding='utf8'))['8081']['feeds']
    events={mapping[e['id']]:e for e in dataset['events']};rows={};ledger=[]
    for path in a.reports:
        report=json.loads(path.read_text(encoding='utf8'));ledger.append({'before':report['before'],'after':report['after']})
        for job in report['jobs']:
            if job['status']!='completed':continue
            response=job['response'];assert response['verification']=='checked' and response['version']==VERSION
            reviewed=validate(response['reviewed_selection'],job['payload']);assert reviewed==response['result']
            for role in ROLES:
                key=job['company_id']+':'+role
                previous=baseline[key]['items'][:5];selected=reviewed[role]
                def metrics(items,id_field):
                    grades=[events[item[id_field]]['relevance'][key] for item in items]
                    relevant=sum(v>0 for v in grades)
                    return {'returned':len(items),'relevant':relevant,'precision_at_5':relevant/5,
                        'precision_at_returned':relevant/len(items) if items else None,
                        'items':[{'event_id':item[id_field],'title':events[item[id_field]]['title'],
                            'gold':grade,'reason':item.get('reason',item.get('reasons'))} for item,grade in zip(items,grades)]}
                rows[key]={'before':metrics(previous,'id'),'after':metrics(selected,'event_id')}
    report={'version':VERSION,'independent':False,'acceptance_eligible':False,'target_met':None,
        'warning':'Reused AI-labelled cohort; list quality only, not factual accuracy of full analyses.',
        'roles':rows,'unchecked_roles':[f'{c}:{r}' for c in dataset['companies'] for r in ROLES if f'{c}:{r}' not in rows],
        'mean_precision_at_5':{phase:sum(v[phase]['precision_at_5'] for v in rows.values())/len(rows) if rows else None for phase in ('before','after')},
        'ledgers':ledger,
        'input_sha256':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in [a.data,a.mapping,a.before,*a.reports]}}
    with a.output.open('x',encoding='utf8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k not in ('roles','input_sha256')},ensure_ascii=False))


if __name__=='__main__':main()
