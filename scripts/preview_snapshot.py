"""Transfer local source/results snapshots without credentials or user sessions.

Import is allowed only into a keyless, offline demo database. Existing feedback,
accounts and profile data are preserved. Conflicting source identities abort it.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from sqlalchemy import DateTime,select
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from app.config import settings
from app.context import company_context
from app.db import SessionLocal
from app.models import Audit,Budget,Company,Document,Event,LlmAllowance,RankingJob,RelevanceAssessment,Run,Usage,User
from app.semantic_ranking import fingerprint

MODELS=(Document,Event,Run,RankingJob,RelevanceAssessment,Usage,Audit,Budget,LlmAllowance)


def dump(row):return {c.name:getattr(row,c.name) for c in row.__table__.columns}


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['export','import']);p.add_argument('path',type=Path);args=p.parse_args()
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.username=='demo'))
        if args.mode=='export':
            if args.path.exists():raise SystemExit('Choose a new snapshot path')
            data={'users':{u.id:u.username for u in db.scalars(select(User))},
                  'contexts':{c:fingerprint(company_context(db,db.get(Company,c),user.company_ids)) for c in ('U_26491','U_989','U_6923')},'tables':{}}
            for model in MODELS:
                stmt=select(model)
                if model in (Run,RankingJob):stmt=stmt.where(model.status.not_in(['queued','running']))
                data['tables'][model.__tablename__]=[dump(r) for r in db.scalars(stmt)]
            with args.path.open('x',encoding='utf8') as f:json.dump(data,f,ensure_ascii=False,default=str)
            print(json.dumps({k:len(v) for k,v in data['tables'].items()}));return
        cfg=settings()
        assert cfg.demo_mode and not cfg.llm_api_key and not cfg.llm_base_url and not cfg.auto_fetch_rss,'Import requires isolated preview'
        data=json.loads(args.path.read_text(encoding='utf8'))
        for company_id,expected in data['contexts'].items():
            assert fingerprint(company_context(db,db.get(Company,company_id),user.company_ids))==expected,'Preview profile differs: '+company_id
        local_users={u.username:u.id for u in db.scalars(select(User))}
        added={}
        for model in MODELS:
            count=0;key_name=next(iter(model.__table__.primary_key.columns)).name
            for values in data['tables'][model.__tablename__]:
                values=dict(values)
                for column in model.__table__.columns:
                    if isinstance(column.type,DateTime) and values.get(column.name):values[column.name]=datetime.fromisoformat(values[column.name])
                if 'user_id' in values:values['user_id']=local_users[data['users'][values['user_id']]]
                existing=db.get(model,values[key_name])
                if existing:
                    if model is Document:
                        assert existing.content_hash==values['content_hash'],'Source changed in preview'
                    elif model is Event:
                        existing.document_ids=list(dict.fromkeys(existing.document_ids+values['document_ids']))
                    elif model is RelevanceAssessment:
                        for name in ('status','result','error','job_id'):setattr(existing,name,values[name])
                    elif model is Budget:existing.spent=max(existing.spent,values['spent'])
                    elif model is LlmAllowance:
                        existing.spent=max(existing.spent,values['spent']);existing.requests=max(existing.requests,values['requests'])
                    continue
                db.add(model(**values));count+=1
            db.flush();added[model.__tablename__]=count
        db.commit();print(json.dumps({'added':added,'credentials_copied':False,'profiles_unchanged':True}))


if __name__=='__main__':main()
