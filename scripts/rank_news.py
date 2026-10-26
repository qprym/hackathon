"""Import a public corpus and run an explicitly bounded neural-selection check.

No call is made unless --max-jobs is positive. Each job evaluates up to five
complete articles for one company and all three roles; it never retries itself.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from app.context import company_context
from app.db import SessionLocal
from app.ingestion import import_document
from app.llm import allowance_status
from app.models import Company,Document,Event,RankingJob,RelevanceAssessment,User
from app.semantic_ranking import article_key,cache_key,enqueue,fingerprint,process_one


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--corpus',type=Path)
    p.add_argument('--companies',nargs='+',required=True)
    p.add_argument('--event-ids',nargs='*')
    p.add_argument('--max-jobs',type=int,default=0)
    p.add_argument('--workers',type=int,choices=(1,2,3),default=1)
    p.add_argument('--resume',action='store_true',help='Explicitly include already queued matching jobs')
    p.add_argument('--continue-partial',action='store_true',help='Keep drafts with local errors for the separate bounded review stage')
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if not 0<=args.max_jobs<=50:raise SystemExit('max-jobs must be 0..50')
    if args.output.exists():raise SystemExit('Choose a new output path')
    dataset=json.loads(args.dataset.read_text(encoding='utf8'))
    records=dataset['events']
    if args.event_ids:
        by_id={e['id']:e for e in records};records=[by_id[key] for key in args.event_ids]
    with SessionLocal() as db:
        before=allowance_status(db)
        imported=0
        if args.corpus:
            corpus=json.loads(args.corpus.read_text(encoding='utf8'))
            for record in corpus['events']:
                if not record['id'].startswith('candidate-'):continue
                for source in record['sources']:
                    _,created=import_document(db,title=source['title'],content=source['content'],kind='news',
                        publisher=source['publisher'],published_at=datetime.fromisoformat(source['published_at'].replace('Z','+00:00')),
                        url=source.get('url'),synthetic=False,
                        ingestion_meta={k:source[k] for k in ('coverage','method','warning','fetched_at','discovery_url') if k in source})
                    imported+=created
        events=db.scalars(select(Event).where(Event.synthetic.is_(False))).all()
        by_doc={doc_id:e for e in events for doc_id in e.document_ids}
        docs=db.scalars(select(Document).where(Document.kind=='news',Document.synthetic.is_(False))).all()
        by_url={d.url:d for d in sorted(docs,key=lambda d:len(d.content)) if d.url}
        mapped={}
        for record in records:
            event=db.get(Event,record['id'])
            if not event:
                document=next((by_url[s['url']] for s in record['sources'] if s.get('url') in by_url),None)
                event=by_doc.get(document.id) if document else None
            if not event:raise ValueError('Event not imported: '+record['id'])
            mapped[record['id']]=event.id
        user=db.scalar(select(User).where(User.username=='demo'))
        job_ids=[]
        for company_id in args.companies:
            if company_id not in user.company_ids:raise ValueError('Company not authorized for demo user')
            company=db.get(Company,company_id)
            result=enqueue(db,user,company,[db.get(Event,key) for key in dict.fromkeys(mapped.values())])
            job_ids.extend(result['job_ids'])
            if args.resume:
                ctx=fingerprint(company_context(db,company,user.company_ids))
                for event_id in mapped.values():
                    event=db.get(Event,event_id);documents=db.scalars(select(Document).where(Document.id.in_(event.document_ids))).all()
                    row=db.get(RelevanceAssessment,cache_key(article_key(event,documents),ctx))
                    if row and row.status=='queued' and row.job_id not in job_ids:job_ids.append(row.job_id)
        print(json.dumps({'imported_public_documents':imported,'new_jobs':len(job_ids),'call_bound':args.max_jobs,'before':before}),flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        bounded=job_ids[:args.max_jobs]
        for offset in range(0,len(bounded),args.workers):
            part=bounded[offset:offset+args.workers]
            list(pool.map(lambda key:process_one(key,defer_review=True),part))
            with SessionLocal() as db:
                jobs=[db.get(RankingJob,key) for key in part]
                for job in jobs:
                    print(json.dumps({'job_id':job.id,'company':job.company_id,'status':job.status,'error':job.error,'usage':allowance_status(db)},ensure_ascii=False),flush=True)
                if any(job.status not in ({'completed','partial'} if args.continue_partial else {'completed'}) for job in jobs):
                    print('Stopped after an incomplete batch; remaining jobs need explicit --resume.',flush=True);break
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.username=='demo'));predictions={}
        for company_id in args.companies:
            company=db.get(Company,company_id);ctx=fingerprint(company_context(db,company,user.company_ids));values={}
            for record_id,event_id in mapped.items():
                event=db.get(Event,event_id);documents=db.scalars(select(Document).where(Document.id.in_(event.document_ids))).all()
                row=db.get(RelevanceAssessment,cache_key(article_key(event,documents),ctx))
                values[record_id]={'status':row.status,'result':row.result,'error':row.error,'cache_key':row.cache_key} if row else {'status':'missing'}
            predictions[company_id]=values
        result={'dataset':str(args.dataset),'mapping':mapped,'companies':args.companies,'before':before,'after':allowance_status(db),
                'job_ids':job_ids,'predictions':predictions}
        with args.output.open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
        print(json.dumps({'requests_this_command':result['after']['requests_used']-before['requests_used'],
                          'cost_this_command':round(result['after']['spent_rub']-before['spent_rub'],6)},ensure_ascii=False))


if __name__=='__main__':main()
