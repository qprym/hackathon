"""Explicitly bounded listwise experiment. Defaults to read-only preflight."""
import argparse,json,sys
from pathlib import Path
from sqlalchemy import select
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.db import SessionLocal
from app.llm import allowance_status
from app.models import Company,RankingJob,User
from app.reading_list import enqueue,enqueue_review,from_database
from app.semantic_ranking import process_one


def main():
    p=argparse.ArgumentParser();p.add_argument('--companies',nargs='+',required=True)
    p.add_argument('--max-jobs',type=int,default=0);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--retry-failed',action='store_true',help='Explicit retry only; preserve the failed job')
    p.add_argument('--request-ceiling',type=int,help='Additional total-request ceiling for this experiment')
    p.add_argument('--resume-review',help='Explicitly review the completed draft from this failed job once')
    a=p.parse_args()
    if a.output.exists():raise SystemExit('Choose a new output path')
    if not 0<=a.max_jobs<=3:raise SystemExit('Max jobs must be 0..3 (at most 6 calls)')
    if a.resume_review and (a.max_jobs!=1 or len(a.companies)!=1):raise SystemExit('Resume exactly one company/job')
    call_bound=a.max_jobs if a.resume_review else 2*a.max_jobs
    report={'jobs':[],'preflight':[]}
    with SessionLocal() as db:
        report['before']=allowance_status(db);user=db.scalar(select(User).where(User.username=='demo'))
        if report['before']['budget_enforced'] and a.request_ceiling is not None and report['before']['requests_used']+call_bound>a.request_ceiling:
            raise SystemExit('Experiment request ceiling would be exceeded; no call made')
        for company_id in a.companies:
            if company_id not in user.company_ids:raise SystemExit('No company access')
            payload=from_database(db,user,db.get(Company,company_id))
            # All documents are sent intact. Reserve estimate includes review and schema.
            source_chars=sum(len(d['text']) for article in payload['articles'] for d in article['documents'])
            report['preflight'].append({'company_id':company_id,'articles':len(payload['articles']),
                'source_chars':source_chars,'payload_utf8_bytes':len(json.dumps(payload,ensure_ascii=False).encode())})
        print(json.dumps({'before':report['before'],'preflight':report['preflight'],'max_calls':call_bound}),flush=True)
        for company_id in a.companies[:a.max_jobs]:
            queued=enqueue_review(db,user,a.resume_review) if a.resume_review else enqueue(db,user,db.get(Company,company_id),retry_failed=a.retry_failed)
            job_id=queued['job_id']
            if db.get(RankingJob,job_id).company_id!=company_id:raise ValueError('Resume company mismatch')
            if not queued['cached']:process_one(job_id)
            db.expire_all();job=db.get(RankingJob,job_id)
            report['jobs'].append({'id':job.id,'company_id':company_id,'status':job.status,'error':job.error,
                'payload':job.payload,'response':job.response})
            report['after']=allowance_status(db)
            print(json.dumps({'company':company_id,'status':job.status,'error':job.error,'after':report['after']},ensure_ascii=False),flush=True)
            if job.status!='completed':break
        report['after']=allowance_status(db)
    with a.output.open('x',encoding='utf8') as f:json.dump(report,f,ensure_ascii=False,default=str,indent=2)


if __name__=='__main__':main()
