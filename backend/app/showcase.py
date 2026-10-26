"""Portable, explicitly synthetic examples. Opening one never calls a model."""
import json
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from .auth import authorize_company
from .bank_relevance import SEARCH_VERSION
from .cashflow import VALIDATION_VERSION
from .context import company_context
from .db import utcnow
from .models import Company, Document, Event, Run
from .retrieval import evidence, event_evidence, rank_event
from .schemas import Insight
from .semantic_ranking import fingerprint
from .validation import restore_citations, validate_insight


@lru_cache
def bundle():
    return json.loads((Path(__file__).resolve().parent.parent / 'fixtures' / 'showcase-v1.json').read_text(encoding='utf8'))


def available_examples(db, user):
    names={c.id:c.name for c in db.scalars(select(Company).where(Company.id.in_(user.company_ids),Company.synthetic.is_(True)))}
    titles={n['id']:n['title'] for n in bundle()['news']}
    return {'version':bundle()['version'],'notice':bundle()['notice'], 'items':[
        {k:row[k] for k in ('id','company_id','role')} | {'company_name':names[row['company_id']], 'title':titles[row['news_id']]}
        for row in bundle()['analyses'] if row['company_id'] in names]}


def open_example(db,user,example_id):
    data=bundle()
    row=next((a for a in data['analyses'] if a['id']==example_id),None)
    if not row or row['company_id'] not in user.company_ids:
        raise HTTPException(404,'Учебный пример не найден')
    company=authorize_company(db,user,row['company_id'])
    spec=next(c for c in data['companies'] if c['id']==company.id)
    if not company.synthetic or any(company.features.get(k,{}).get('value')!=v for k,v in spec['features'].items()):
        raise HTTPException(409,'Учебный профиль изменён; готовый пример больше не соответствует его данным.')
    docs=[]
    for kind,key in (('news','news_id'),('bank','bank_id')):
        source=next(s for s in data[kind] if s['id']==row[key])
        doc=db.scalar(select(Document).where(Document.synthetic.is_(True),Document.kind==kind,
            Document.title==source['title'],Document.content==source['content']).order_by(Document.published_at.desc()))
        if not doc:raise HTTPException(409,'Исходный материал примера отсутствует или изменён. Требуется исходный учебный набор.')
        docs.append(doc)
    event=next((e for e in db.scalars(select(Event).where(Event.synthetic.is_(True))) if docs[0].id in e.document_ids),None)
    if not event:raise HTTPException(409,'Учебное событие отсутствует.')
    context=company_context(db,company,user.company_ids)
    sources=event_evidence(db,event,document_ids=[docs[0].id])
    bank=evidence(docs[1],0,{'text':docs[1].content,'page':None})
    bank['relevance']={'level':'direct','reason':'Источник заранее указан в синтетическом примере; это не оценка модели.'}
    sources.append(bank)
    insight=restore_citations(Insight.model_validate(row['insight']),{'news':sources[0]['id'],'bank':bank['id']})
    issues=validate_insight(insight,sources,context,event_source_ids={sources[0]['id']})
    if issues:raise HTTPException(409,'Готовый пример не прошёл проверку оснований: '+'; '.join(issues))
    scope=sorted(set(user.company_ids))
    key=fingerprint([data['version'],row,context,user.id,scope,[(d.id,d.content_hash) for d in docs],SEARCH_VERSION,VALIDATION_VERSION])
    existing=db.scalar(select(Run).where(Run.cache_key==key,Run.status=='completed'))
    if existing:return {'run_id':existing.id,'cached':True,'fixture':data['version']}
    result=insight.model_dump() | {'evidence':sources,'context_features':context['features'],
        'verification':'checked','search_version':SEARCH_VERSION,'validation_version':VALIDATION_VERSION,
        'mode':'demo','fixture':data['version'],'fixture_notice':data['notice'],
        'role':row['role'],'company_name':company.name,'ranking':rank_event(event,context,row['role'])}
    run=Run(user_id=user.id,company_id=company.id,event_id=event.id,role=row['role'],access_scope=scope,
        cache_key=key,status='completed',stage='Готовый учебный пример',result=result,finished_at=utcnow(),
        trace=[{'step':'Открытие готового примера','at':utcnow().isoformat()+'Z',
            'details':{'fixture':data['version'],'example':row['id'],'model_called':False,'references_checked':True}}])
    db.add(run);db.commit()
    return {'run_id':run.id,'cached':False,'fixture':data['version']}
