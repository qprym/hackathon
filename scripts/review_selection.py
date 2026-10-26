"""Bounded semantic review and export of a previously collected selection cohort."""
import argparse
import json
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from app.config import settings
from app.context import company_context
from app.db import SessionLocal
from app.llm import allowance_status
from app.models import Company,Document,Event,RankingJob,RelevanceAssessment,User
from app.semantic_ranking import SELECTION_VERSION,REVIEW_VERSION,article_key,cache_key,fingerprint,review_cached


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--cohort',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-jobs',type=int,default=0)
    p.add_argument('--workers',type=int,choices=(1,2),default=1)
    args=p.parse_args()
    if not 0<=args.max_jobs<=6:raise SystemExit('max-jobs must be 0..6')
    if args.output.exists():raise SystemExit('Choose a new output path')
    cohort=json.loads(args.cohort.read_text(encoding='utf8'));mapping=cohort['mapping'];companies=cohort['companies']
    all_keys={};plans=[];contexts={}
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.username=='demo'));user_id=user.id;before=allowance_status(db)
        for company_id in companies:
            if company_id not in user.company_ids:raise PermissionError('Company unavailable')
            context=company_context(db,db.get(Company,company_id),user.company_ids);contexts[company_id]=fingerprint(context)
            all_keys[company_id]={};pending=[]
            for source_id,event_id in mapping.items():
                event=db.get(Event,event_id);docs=db.scalars(select(Document).where(Document.id.in_(event.document_ids))).all()
                key=cache_key(article_key(event,docs),fingerprint(context));row=db.get(RelevanceAssessment,key)
                if not row or row.status=='queued':raise ValueError('Complete classification first: '+source_id)
                all_keys[company_id][source_id]=key
                if (row.result or {}).get('review',{}).get('version')!=REVIEW_VERSION:pending.append(key)
            for offset in range(0,len(pending),25):plans.append((company_id,pending[offset:offset+25],user_id))
    print(json.dumps({'before':before,'review_jobs':len(plans),'bound':args.max_jobs}),flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        bounded=plans[:args.max_jobs]
        for offset in range(0,len(bounded),args.workers):
            ids=list(pool.map(lambda a:review_cached(*a),bounded[offset:offset+args.workers]))
            with SessionLocal() as db:
                jobs=[db.get(RankingJob,key) for key in ids]
                for job in jobs:print(json.dumps({'job_id':job.id,'company':job.company_id,'status':job.status,'error':job.error,'usage':allowance_status(db)},ensure_ascii=False),flush=True)
                if any(job.status!='completed' for job in jobs):break
    with SessionLocal() as db:
        predictions={}
        for company_id,keys in all_keys.items():
            predictions[company_id]={}
            for event_id,key in keys.items():
                row=db.get(RelevanceAssessment,key)
                predictions[company_id][event_id]={'status':row.status,'result':row.result,'error':row.error,'cache_key':key}
        data={'selection_version':SELECTION_VERSION,'review_version':REVIEW_VERSION,'model_id':settings().llm_analysis_id,
              'context_fingerprints':contexts,'mapping':mapping,'companies':companies,'before':before,'after':allowance_status(db),'predictions':predictions}
        with args.output.open('x',encoding='utf8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
        print(json.dumps({'requests_this_command':data['after']['requests_used']-before['requests_used'],'after':data['after']}))


if __name__=='__main__':main()
