import hashlib
import json
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session
from .auth import admin, authorize_company, current_user, make_session, token_hash, verify_password
from .config import settings,settings_scope,SettingsUnavailable
from .llm_settings import ConnectionInput,public_settings,save_settings,reset_settings
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from .context import company_context
from .db import SessionLocal, engine, get_db, initialize_development_schema, utcnow
from .ingestion import FEEDS, extract_pdf, import_csv, import_document
from .models import Audit, AuthSession, Budget, Company, Document, Event, Feedback, Link, Run, Usage, User, RankingJob, RelevanceAssessment
from .retrieval import TOPIC_NAMES, RANKING_VERSION, NEWS_CONTEXT_VERSION, rank_event, search_documents
from .news_focus import source_focus
from .event_groups import group_records, diversified
from .feed_selection import assemble_feed, ORDERING_VERSION
from types import SimpleNamespace
from .quality import mode_metrics
from .bank_relevance import SEARCH_VERSION
from .schemas import Analyze, FeedbackInput, Login, NewsInput, Question, Role, FeedPage
from .seed import seed
from .worker import work_loop
from .feeds import feed_status, refresh_feed
from .llm import allowance_status, remote_budget_enabled
from .cashflow import VALIDATION_VERSION
from .semantic_ranking import SELECTION_VERSION, article_key, fingerprint, feed_ranking, cache_key as assessment_key, enqueue as enqueue_ranking
from pydantic import BaseModel, Field


@asynccontextmanager
async def lifespan(app):
    # Production PostgreSQL schema is owned by Alembic; SQLite is a development convenience.
    if engine.dialect.name == "sqlite":
        initialize_development_schema()
    if settings().seed_demo:
        with SessionLocal() as db:
            seed(db)
    stop = threading.Event()
    worker = None
    if settings().inline_worker:
        worker = threading.Thread(target=work_loop, args=(stop,), daemon=True)
        worker.start()
    yield
    stop.set()
    if worker:
        worker.join(timeout=3)


app = FastAPI(title="Альфа · Контекст", version="0.3.0", lifespan=lifespan,
              docs_url='/api/docs',openapi_url='/api/openapi.json',redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=settings().allowed_origins.split(","),
                   allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Alfa-Request"])


@app.middleware("http")
async def browser_safety(request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        # Custom header prevents cross-site form CSRF; CORS protects cross-origin scripted requests.
        if request.headers.get("x-alfa-request") != "1":
            return JSONResponse(
                {"detail": "Отсутствует защитный заголовок запроса"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin not in settings().allowed_origins.split(","):
            return JSONResponse(
                {"detail": "Источник запроса не разрешен"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "mode": "demo" if settings().demo_mode else "live", "version": "0.1.0"}


@app.middleware('http')
async def configuration_snapshot(request,call_next):
    try:
        with settings_scope():return await call_next(request)
    except SettingsUnavailable:
        return JSONResponse({'detail':'Не удалось прочитать серверные настройки LLM.'},status_code=503)


@app.exception_handler(RequestValidationError)
async def redact_settings_validation(request,exc):
    if request.url.path.startswith('/api/admin/llm-settings'):
        fields=sorted({str(part) for err in exc.errors() for part in err['loc'] if part in ConnectionInput.model_fields})
        return JSONResponse({'detail':'Проверьте формат и значения полей настроек'+(': '+', '.join(fields) if fields else '')+'.'},status_code=422)
    return await request_validation_exception_handler(request,exc)


@app.get('/api/admin/llm-settings')
def get_llm_settings(user:User=Depends(admin)):
    return public_settings()


@app.post('/api/admin/llm-settings')
def update_llm_settings(body:ConnectionInput,user:User=Depends(admin),db:Session=Depends(get_db)):
    try:return save_settings(db,user,body)
    except OSError:raise HTTPException(503,'Не удалось сохранить настройки в серверном хранилище.') from None


class SettingsRevision(BaseModel):
    revision:str=Field(max_length=100)


@app.post('/api/admin/llm-settings/reset')
def restore_llm_environment(body:SettingsRevision,user:User=Depends(admin),db:Session=Depends(get_db)):
    return reset_settings(db,user,body.revision)


def user_info(user):
    return {"id": user.id, "name": user.name, "username": user.username,
            "company_ids": user.company_ids, "is_admin": user.is_admin,
            "mode": "demo" if settings().demo_mode else "live"}


@app.post("/api/auth/login")
def login(body: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    # Persisted limits also apply across process restarts; never trust X-Forwarded-For here.
    actor = request.client.host if request.client else "unknown"
    count = db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "login_failed", Audit.actor == actor,
        Audit.created_at > utcnow() - timedelta(minutes=10)))
    if count >= 15:
        raise HTTPException(429, "Слишком много попыток. Повторите через 10 минут.")
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not verify_password(body.password, user.password_hash):
        db.add(Audit(action="login_failed", actor=actor, details={}))
        db.commit()
        raise HTTPException(401, "Неверный логин или пароль")
    token = make_session(db, user)
    response.set_cookie("alfa_session", token, httponly=True, secure=settings().cookie_secure,
                        samesite="lax", max_age=43200, path="/")
    return user_info(user)


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    session = db.get(AuthSession, token_hash(request.cookies.get("alfa_session", "")))
    if session:
        db.delete(session)
        db.commit()
    response.delete_cookie("alfa_session", path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return user_info(user)


@app.get("/api/companies")
def companies(user: User = Depends(current_user), db: Session = Depends(get_db)):
    result=[]
    for c in db.scalars(select(Company).where(Company.id.in_(user.company_ids))).all():
        ctx_key=fingerprint(company_context(db,c,user.company_ids))
        rows=[r for r in db.scalars(select(RelevanceAssessment).where(RelevanceAssessment.company_id==c.id,
            RelevanceAssessment.context_key==ctx_key,RelevanceAssessment.version==SELECTION_VERSION,
            RelevanceAssessment.model_id==settings().llm_analysis_id)) if r.cache_key==assessment_key(r.article_key,ctx_key)]
        ready_roles=[role for role in ('CEO','CFO','TREASURER') if any(feed_ranking(r,role)['eligible'] for r in rows)]
        # A complete reviewed list supersedes preliminary grades, including an empty list.
        if db.scalar(select(RankingJob.id).where(RankingJob.company_id==c.id,RankingJob.status=='completed',
                RankingJob.payload['purpose'].as_string()=='full_feed').limit(1)):
            from . import full_selection
            payload=full_selection.from_database(db,user,c)
            entries=[{'id':a['event_id'],'score':0} for a in payload['articles']]
            for role in ('CEO','CFO','TREASURER'):
                selected,_=full_selection.apply_cached(db,c.id,payload,entries,role)
                if selected is not None:
                    ready_roles=[r for r in ready_roles if r!=role]
                    if selected:ready_roles.append(role)
        result.append({"id":c.id,"name":c.name,"industry":c.industry,"region":c.region,
                       "synthetic":c.synthetic,"ready_roles":ready_roles})
    return result


@app.get('/api/examples')
def examples(user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .showcase import available_examples
    return available_examples(db,user)


@app.post('/api/examples/{example_id}/open')
def show_example(example_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .showcase import open_example
    return open_example(db,user,example_id)


@app.get("/api/companies/{company_id}/context")
def context(company_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    company = authorize_company(db, user, company_id)
    return company_context(db, company, user.company_ids)


@app.get('/api/companies/{company_id}/relations')
def relations(company_id:str,q:str='',direction:Literal['all','incoming','outgoing']='all',
              offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100),
              user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .context import related_context
    company=authorize_company(db,user,company_id)
    return related_context(db,company,user.company_ids,query=q,direction=direction,offset=offset,limit=limit)


@app.get("/api/feed",response_model=FeedPage)
def feed(company_id: str, role: Role = "CFO", topic: str | None = None, corpus: Literal["real", "synthetic"] = "real",
         q: str = "",
         scope: Literal['personal','all'] | None = None, feed_version: str | None = None,
         offset: int = Query(default=0,ge=0), limit: int = Query(default=20,ge=1,le=100),
         user: User = Depends(current_user), db: Session = Depends(get_db)):
    company = authorize_company(db, user, company_id)
    ctx = company_context(db, company, user.company_ids)
    if corpus == "synthetic" and not company.synthetic:
        raise HTTPException(422, "Учебные события доступны только для учебных профилей")
    from . import feed_pages, full_selection
    from .feed_selection import fold_editions
    search_scope=scope or ('all' if q.strip() else 'personal')
    query={'role':role,'topic':topic,'corpus':corpus,'q':q.strip(),'scope':search_scope}
    if feed_version:
        return feed_pages.read(db,user,company_id,ctx,query,feed_version,offset,limit)
    if offset:
        raise HTTPException(422,'Для следующей страницы необходима версия подборки feed_version')
    stmt = select(Event).where(Event.synthetic == (corpus == "synthetic"))
    events = db.scalars(stmt.order_by(Event.published_at.desc(), Event.id.desc())).all()
    entries = []
    ranking_as_of = utcnow()
    doc_ids = {doc_id for event in events for doc_id in event.document_ids}
    documents = {d.id:d for d in db.scalars(select(Document).where(Document.id.in_(doc_ids)))} if doc_ids else {}
    assessments={r.article_key:r for r in db.scalars(select(RelevanceAssessment).where(
        RelevanceAssessment.company_id==company.id,RelevanceAssessment.context_key==fingerprint(ctx),
        RelevanceAssessment.version==SELECTION_VERSION,RelevanceAssessment.model_id==settings().llm_analysis_id))
        if r.cache_key==assessment_key(r.article_key,fingerprint(ctx))} if corpus=='real' else {}
    selection_counts={'completed':0,'queued':0,'failed':0,'not_requested':0}
    records = [{'id':e.id,'title':e.title,'published_at':e.published_at.isoformat(),'document_ids':e.document_ids,
                'sources':[{'url':d.url,'content':d.content} for key in e.document_ids if (d:=documents.get(key))]} for e in events]
    groups = group_records(records)
    for event in events:
        event_docs = [documents[k] for k in event.document_ids if k in documents]
        doc = max(event_docs, key=lambda d:len(d.content), default=None)
        focus = SimpleNamespace(title=event.title, topics=event.topics, published_at=event.published_at,
                                focus_text=source_focus(event.title, event_docs))
        if corpus=='real':
            assessment=assessments.get(article_key(event,event_docs))
            ranking=feed_ranking(assessment,role)
            for ground in ranking.get('ranking_grounds',[]):
                ground['document_id']=next((d.id for d in event_docs if d.content_hash==ground['content_hash']),None)
            selection_counts[ranking['ranking_status']]+=1
        else:
            ranking=rank_event(focus,ctx,role,as_of=ranking_as_of)
            ranking.update(ranking_method='demo_rules',ranking_status='completed')
        entries.append({"id": event.id, "title": event.title, "topics": event.topics,
            "event_group":groups[event.id],
            "document_id":doc.id if doc else None,
            "published_at": event.published_at.isoformat() + "Z", "synthetic": event.synthetic,
            "summary": doc.content[:230] if doc else "", "publisher": doc.publisher if doc else "",
            "source_count": len({d.publisher.casefold().strip() for d in event_docs}), **ranking})
    entries.sort(key=lambda item: (item["score"], item["published_at"], item['id']), reverse=True)
    candidates=[item for item in entries if item['eligible']]
    items=fold_editions(candidates) if corpus=='real' else diversified(candidates)
    list_selection=None
    ordering_version='model_score_with_editions' if corpus=='real' else 'model_score'
    if corpus=='real':
        from .reading_list import make_payload, apply_cached
        payload=make_payload(ctx,events,documents,assessments)
        selected,list_selection=apply_cached(db,company.id,payload,candidates,role)
        if selected is not None:
            # Historical shortlists remain evidence of the old run. They do not cap the full feed.
            chosen={e['id'] for e in selected}
            items=selected+[e for e in items if e['id'] not in chosen] if selected else [];ordering_version=list_selection['version']
            list_selection={**list_selection,'coverage':'partial','historical':True}
        full_payload=full_selection.from_database(db,user,company)
        complete,full_state=full_selection.apply_cached(db,company.id,full_payload,entries,role)
        if complete is not None:
            items=complete;list_selection=full_state;ordering_version=full_selection.VERSION
        elif full_state['status']!='not_requested':
            list_selection=full_state
    selected_count=len(items)
    if not events:personal_status='no_sources'
    elif corpus=='synthetic' or (list_selection and list_selection['status']=='completed' and not list_selection.get('historical')):
        personal_status='ready'
    elif selection_counts['completed']:
        personal_status='ready' if selection_counts['completed']==len(events) else 'partial'
    elif selection_counts['queued'] or (list_selection and list_selection['status'] in ('queued','running')):
        personal_status='processing'
    elif selection_counts['failed'] or (list_selection and list_selection['status']=='failed'):
        personal_status='failed'
    else:personal_status='not_processed'
    if search_scope=='all':
        ordered_ids={e['id'] for e in items}
        items=items+[e for e in entries if e['id'] not in ordered_ids]
    # Facets describe the complete scoped collection, not the current page or selected topic.
    available_topics=[key for key in TOPIC_NAMES if any(key in item['topics'] for item in items)]
    if topic:items=[item for item in items if topic in item['topics']]
    if q.strip():
        needle=q.strip().casefold()
        matched={e.id for e in events if needle in e.title.casefold() or any(needle in documents[k].content.casefold() for k in e.document_ids if k in documents)}
        items=[item for item in items if item['id'] in matched]
    payload={"items": items, "topics": TOPIC_NAMES, "company_id": company_id, "role": role, "corpus": corpus,
            'available_topics':available_topics,
            'scope':search_scope,
            'personalization':{'status':personal_status,'selected_count':selected_count,
                               'article_count':len(events),'assessed_count':selection_counts['completed']},
            "ranking_version":SELECTION_VERSION if corpus=='real' else RANKING_VERSION,
            "ordering_version":ordering_version,"list_selection":list_selection,
            "selection":{'method':'llm' if corpus=='real' else 'demo_rules','model':settings().llm_analysis_id,
                'total':len(events),**selection_counts,'can_request':not settings().demo_mode and settings().neural_ranking_worker},
            'pipeline':{'automatic':settings().auto_personalization and settings().llm_provider_mode=='local',
                'model_available':bool(settings().llm_base_url) and not settings().demo_mode,
                'provider_mode':settings().llm_provider_mode}}
    return feed_pages.save(db,user,company_id,ctx,query,payload,offset,limit)


class RankNewsRequest(BaseModel):
    company_id:str
    event_ids:list[str]=Field(default_factory=list,max_length=50)


class ReadingListRequest(BaseModel):
    company_id:str
    retry_failed:bool=False


@app.post('/api/reading-list',status_code=202)
def select_reading_list(body:ReadingListRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    company=authorize_company(db,user,body.company_id)
    if settings().demo_mode or not settings().neural_ranking_worker:
        raise HTTPException(409,'Сравнительный отбор отключён администратором; сохранённые подборки доступны.')
    from .full_selection import enqueue
    from .llm import BudgetExceeded
    try:return enqueue(db,user,company,retry_failed=body.retry_failed)
    except BudgetExceeded as exc:raise HTTPException(429,str(exc))
    except ValueError as exc:raise HTTPException(422,str(exc))


@app.post('/api/ranking',status_code=202)
def rank_news(body:RankNewsRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    company=authorize_company(db,user,body.company_id)
    if settings().demo_mode:
        raise HTTPException(409,'На этом стенде отключён платный API. Доступны сохранённые оценки DeepSeek.')
    if not settings().neural_ranking_worker:
        raise HTTPException(409,'Фоновый нейросетевой отбор отключён администратором.')
    allowance=allowance_status(db)
    if allowance['budget_enforced'] and (allowance['requests_remaining']<2 or allowance['spent_rub']>=allowance['test_limit_rub']):
        raise HTTPException(429,'Лимит обращений или общий денежный бюджет исчерпан.')
    stmt=select(Event).where(Event.synthetic.is_(False)).order_by(Event.published_at.desc())
    if body.event_ids:stmt=stmt.where(Event.id.in_(body.event_ids))
    events=db.scalars(stmt.limit(50 if body.event_ids else 10)).all()
    return enqueue_ranking(db,user,company,events,max_jobs=allowance['requests_remaining']//2 if allowance['budget_enforced'] else None)


@app.get('/api/ranking/jobs/{job_id}')
def ranking_job(job_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    job=db.get(RankingJob,job_id)
    if not job or job.user_id!=user.id:raise HTTPException(404,'Задача не найдена')
    authorize_company(db,user,job.company_id)
    return {'id':job.id,'status':job.status,'error':job.error,'articles':len(job.cache_keys)}


@app.get("/api/feeds/status")
def sources_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return feed_status(db)


def create_run(db, user, body, question=None, parent=None, single_pass=False):
    company = authorize_company(db, user, body.company_id)
    event = db.get(Event, body.event_id)
    if not event:
        raise HTTPException(404, "Событие не найдено")
    if event.synthetic and not company.synthetic:
        raise HTTPException(422, "Учебные события нельзя использовать для реальных компаний")
    # Corpus and relationship versions invalidate previously generated explanations.
    from .full_selection import verified_source_ids
    source_ids=verified_source_ids(db,user,company,event)
    documents = db.execute(select(Document.id, Document.content_hash).where(Document.synthetic == event.synthetic,
                           or_(Document.id.in_(source_ids),Document.kind=='bank'))
                           .order_by(Document.id)).all()
    context_version = company_context(db, company, user.company_ids)
    from .context import related_context
    relation_version = related_context(db,company,user.company_ids,limit=0)
    relation_rows = db.execute(select(Link.id,Link.amount,Link.count,Link.details,Link.source_id,Link.target_id).where(
        or_(Link.source_id==company.id,Link.target_id==company.id)).order_by(Link.id)).all()
    related_ids={key for row in relation_rows for key in (row.source_id,row.target_id)} & set(user.company_ids)
    related_profiles=db.execute(select(Company.id,Company.features,Company.industry,Company.region,Company.updated_at)
        .where(Company.id.in_(related_ids),Company.synthetic==company.synthetic).order_by(Company.id)).all()
    # Include inline prompts as well as policy constants; no forgotten manual version bump.
    instruction_revision=hashlib.sha256(b''.join((Path(__file__).parent/name).read_bytes()
        for name in ('agent.py','review.py','cashflow.py','forecast.py'))).hexdigest()
    access_scope = sorted(set(user.company_ids))
    def key_for_mode(demo_mode):
        return hashlib.sha256(json.dumps([user.id, access_scope, body.model_dump(), company.features, str(company.updated_at),
            [list(d) for d in documents], context_version, question, parent if question else None, demo_mode,
            settings().llm_analysis_id, settings().llm_extraction_id, settings().llm_provider_mode,settings().llm_model_revision,
            relation_version,[list(r) for r in relation_rows],[list(r) for r in related_profiles],instruction_revision,
            "prompt-v20", SEARCH_VERSION, VALIDATION_VERSION, RANKING_VERSION, NEWS_CONTEXT_VERSION], sort_keys=True, default=str).encode()).hexdigest()
    key=key_for_mode(settings().demo_mode)
    if settings().preview_cached_only and not event.synthetic:
        existing=db.scalar(select(Run).where(Run.cache_key==key_for_mode(False),Run.status=='completed').order_by(Run.created_at.desc()))
        if existing:return {'run_id':existing.id,'cached':True}
        if not question:
            historical=db.scalar(select(Run).where(Run.user_id==user.id,Run.company_id==company.id,Run.event_id==event.id,
                Run.role==body.role,Run.question.is_(None),Run.status=='completed',Run.result['mode'].as_string()=='live')
                .order_by(Run.created_at.desc()).limit(1))
            if historical and set(historical.access_scope or []).issubset(user.company_ids):
                return {'run_id':historical.id,'cached':True,'historical':True}
        raise HTTPException(409,'На этом стенде доступны сохранённые разборы DeepSeek. Для этой компании, роли и статьи готового разбора нет; новый платный вызов отключён.')
    existing = db.scalar(select(Run).where(Run.cache_key == key, Run.status.in_(["queued", "running", "completed"])).order_by(Run.created_at.desc()))
    if existing and not (parent and not question and existing.status == 'completed' and (existing.result or {}).get('verification') == 'insufficient'):
        return {"run_id": existing.id, "cached": existing.status == "completed"}
    if not settings().demo_mode and remote_budget_enabled() and (question or not parent) and allowance_status(db)['requests_remaining'] < 5:
        raise HTTPException(429, 'Для нового разбора или вопроса нужны как минимум пять обращений. Оставшаяся квота сохранена; готовые результаты доступны из кеша.')
    pending = db.scalar(select(func.count()).select_from(Run).where(Run.user_id == user.id, Run.status.in_(["queued", "running"])))
    if pending >= 5:
        raise HTTPException(429, "Дождитесь завершения текущих анализов")
    run = Run(user_id=user.id, company_id=company.id, event_id=event.id, role=body.role,
              question=question, parent_id=parent, cache_key=key, access_scope=access_scope)
    run.trace=[{'step':'Состав события','at':utcnow().isoformat()+'Z','details':{'document_ids':source_ids}}]
    run.trace.append({'step':'Снимок конфигурации','at':utcnow().isoformat()+'Z','details':{
        'mode':'demo' if settings().demo_mode else 'live','revision':settings().llm_model_revision,
        'model':settings().llm_analysis_id,'provider':settings().llm_provider_mode}})
    if single_pass:
        run.trace = [{'step': 'Режим пересчёта', 'at': utcnow().isoformat() + 'Z', 'details': {'max_attempts': 1,
            'note': 'Свежий поиск, один синтез и независимая проверка; максимум два обращения без платных повторов.'}}] + run.trace
    db.add(run)
    db.commit()
    return {"run_id": run.id, "cached": False}


@app.post("/api/analyses", status_code=202)
def analyze(body: Analyze, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return create_run(db, user, body)


def authorized_run(db, user, run_id):
    run = db.get(Run, run_id)
    if not run or run.user_id != user.id or run.company_id not in user.company_ids:
        raise HTTPException(404, "Анализ не найден")
    if not run.access_scope or not set(run.access_scope).issubset(user.company_ids):
        raise HTTPException(409, "Права доступа изменились. Запустите новый анализ из ленты.")
    return run


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run = authorized_run(db, user, run_id)
    rating = db.scalar(select(Feedback).where(Feedback.run_id == run_id, Feedback.user_id == user.id))
    # Trace available to reviewers but cannot expose IDs of inaccessible related companies.
    steps = [{**s, "details": {k: v for k, v in s["details"].items() if k != "counterparties"}} for s in run.trace] if user.is_admin else []
    return {"id": run.id, "status": run.status, "stage": run.stage, "trace": steps,
            "result": run.result, "error": run.error, "question": run.question, "role": run.role,
            "company_id": run.company_id, "event_id": run.event_id,
            "event_title": db.get(Event, run.event_id).title,
            "feedback": {'category': rating.category, 'comment': rating.comment} if rating else None,
            "validation_outdated": bool(run.result and run.result.get('validation_version') != VALIDATION_VERSION),
            "search_outdated": bool(run.result and run.result.get('search_version') != SEARCH_VERSION)}


@app.get('/api/runs/{run_id}/bank-research')
def current_bank_research(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run = authorized_run(db, user, run_id)
    event = db.get(Event, run.event_id)
    sources = search_documents(db, event.title, kind='bank', before=event.published_at,
                               synthetic=event.synthetic, limit=6, focus=event.title)
    return {'search_version': SEARCH_VERSION, 'sources': sources,
            'has_direct': any(e['relevance']['level'] == 'direct' for e in sources)}


@app.post("/api/insights/{run_id}/questions", status_code=202)
def ask(run_id: str, body: Question, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run = authorized_run(db, user, run_id)
    if run.status != "completed":
        raise HTTPException(409, "Основной анализ еще не завершен")
    return create_run(db, user, Analyze(company_id=run.company_id, event_id=run.event_id, role=run.role), body.question, run.id)


@app.post("/api/insights/{run_id}/feedback")
def feedback(run_id: str, body: FeedbackInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    authorized_run(db, user, run_id)
    record = db.scalar(select(Feedback).where(Feedback.run_id == run_id, Feedback.user_id == user.id))
    if not record:
        record = Feedback(run_id=run_id, user_id=user.id)
        db.add(record)
    record.category, record.comment = body.category, body.comment
    db.commit()
    return {"ok": True}


@app.post('/api/insights/{run_id}/retry', status_code=202)
def retry_insight(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run = authorized_run(db, user, run_id)
    rejected = run.status == 'completed' and (run.result or {}).get('verification') == 'insufficient'
    interrupted_draft = run.status == 'failed' and any(step['step'] == 'Черновик анализа' for step in run.trace)
    if not rejected and not interrupted_draft:
        raise HTTPException(409, 'Повтор доступен для отклонённого разбора или сбоя после получения черновика')
    if not settings().demo_mode and remote_budget_enabled() and allowance_status(db)['requests_remaining'] < 4:
        raise HTTPException(429, 'Для исправления с корректирующим циклом нужны четыре оставшихся обращения. Общий лимит не увеличен.')
    return create_run(db, user, Analyze(company_id=run.company_id, event_id=run.event_id, role=run.role), parent=run.id)


@app.post('/api/insights/{run_id}/refresh', status_code=202)
def refresh_insight(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run = authorized_run(db, user, run_id)
    if (run.status != 'completed' or (run.result or {}).get('verification') != 'checked'
            or (run.result.get('search_version') == SEARCH_VERSION and run.result.get('validation_version') == VALIDATION_VERSION)):
        raise HTTPException(409, 'Пересчёт доступен для проверенного разбора с прежней версией поиска или проверки')
    if not settings().demo_mode and remote_budget_enabled() and allowance_status(db)['requests_remaining'] < 2:
        raise HTTPException(429, 'Для пересчёта и независимой проверки нужны два оставшихся обращения.')
    return create_run(db, user, Analyze(company_id=run.company_id, event_id=run.event_id, role=run.role),
                      parent=run.id, single_pass=True)


@app.get("/api/sources/{source_id}")
def source(source_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = db.get(Document, source_id)
    if not doc:
        raise HTTPException(404, "Источник не найден")
    meta=dict(doc.ingestion_meta)
    if meta.get('original_file') and not meta.get('pages'):
        count=meta.get('page_count',max((c.get('page') or 0 for c in doc.chunks),default=0))
        meta['pages']=[]
        for number in range(1,count+1):
            chunks=[c for c in doc.chunks if c.get('page')==number]
            meta['pages'].append({'number':number,'text_status':'empty' if not chunks else
                'ocr' if any(c.get('extraction')=='ocr' for c in chunks) else 'extracted',
                'visual_status':'not_verified','numeric_tables_status':'not_verified'})
    return {"id": doc.id, "title": doc.title, "kind": doc.kind, "publisher": doc.publisher,
            "url": doc.url, "published_at": doc.published_at.isoformat() + "Z", "content": doc.content,
            "chunks": doc.chunks, "synthetic": doc.synthetic, "ingestion": meta}


@app.get("/api/library")
def library(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": d.id, "title": d.title, "publisher": d.publisher,
        "published_at": d.published_at.isoformat() + 'Z', "synthetic": d.synthetic,
        "pages": d.ingestion_meta.get('page_count', len({c.get('page') for c in d.chunks if c.get('page')})), "extraction": d.ingestion_meta.get('extraction', 'text'),
        "date_kind":d.ingestion_meta.get('date_kind','publication'), "date_source":d.ingestion_meta.get('date_source','Дата загрузившего материал')}
        for d in db.scalars(select(Document).where(Document.kind == 'bank').order_by(Document.synthetic, Document.published_at.desc()).limit(200))]


@app.post("/api/admin/news")
def add_news(body: NewsInput, user: User = Depends(admin), db: Session = Depends(get_db)):
    try:
        params = body.model_dump()
        params["url"] = str(body.url) if body.url else None
        doc, created = import_document(db, **params)
        db.add(Audit(action="document_import", actor=user.id, details={"document_id": doc.id, "created": created}))
        db.commit()
        return {"document_id": doc.id, "created": created}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/admin/import/csv")
def upload_csv(file: UploadFile = File(...), synthetic: bool = Form(False), user: User = Depends(admin), db: Session = Depends(get_db)):
    raw = file.file.read(64_000_001)
    if len(raw) > 64_000_000:
        raise HTTPException(413, "Максимум 64 МБ")
    try:
        report = import_csv(db, raw, Path(file.filename or "data.csv").name, synthetic=synthetic)
        user.company_ids = list(dict.fromkeys([*user.company_ids, *report["company_ids"][:100]]))
        report['company_count'] = len(report['company_ids'])
        if len(report['company_ids']) > 100:
            report['warnings'].append('Для просмотра доступны первые 100 импортированных компаний. Для выдачи доступа к другим профилям используйте локальную команду case_import --grant.')
        report['company_ids'] = report['company_ids'][:100]
        db.add(Audit(action="csv_import", actor=user.id, details={k: v for k, v in report.items() if k != "company_ids"}))
        db.commit()
        return report
    except (ValueError, UnicodeError) as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/admin/import/pdf")
def upload_pdf(file: UploadFile = File(...), title: str = Form(...), published_at: datetime = Form(...),
    synthetic: bool = Form(False), user: User = Depends(admin), db: Session = Depends(get_db)):
    raw = file.file.read(64_000_001)
    if len(raw) > 64_000_000:
        raise HTTPException(413, "Максимум 64 МБ")
    try:
        content, chunks, pages = extract_pdf(raw, with_pages=True)
        original = hashlib.sha256(raw).hexdigest() + '.pdf'
        Path('uploads').mkdir(exist_ok=True)
        Path('uploads', original).write_bytes(raw)
        doc, created = import_document(db, title=title, content=content, chunks=chunks, kind="bank",
            publisher="Синтетический пример" if synthetic else "Альфа-Банк · материалы кейса",
            published_at=published_at, synthetic=synthetic, ingestion_meta={"original_file": original, "page_count":len(pages),
                "coverage": "provided", "pages":pages, "extraction": "ocr" if any(c.get('extraction') == 'ocr' for c in chunks) else "pdf",
                "warning": "Текст PDF/OCR: числа, таблицы и графики необходимо сверять с оригиналом."})
        return {"document_id": doc.id, "created": created,
                "warning": "Извлечен текст. Графики и таблицы нужно сверить с оригиналом; выводы не опираются на нераспознанные изображения."}
    except Exception as exc:
        db.rollback()
        raise HTTPException(422, "Не удалось импортировать PDF: " + (str(exc)[:200] if isinstance(exc, ValueError) else "проверьте формат")) from exc


@app.get("/api/sources/{source_id}/original")
def original_pdf(source_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = db.get(Document, source_id)
    name = doc.ingestion_meta.get('original_file', '') if doc else ''
    path = Path('uploads') / Path(name).name
    if not name or not path.is_file():
        raise HTTPException(404, "Оригинал не сохранён")
    return FileResponse(path, media_type='application/pdf', filename='bank-research.pdf')


@app.post("/api/admin/feeds/{key}")
def sync_feed(key: str, user: User = Depends(admin), db: Session = Depends(get_db)):
    if key not in FEEDS:
        raise HTTPException(404, "Источник не найден")
    report = refresh_feed(key, force=True, actor=user.id)
    if report["status"] == "error":
        raise HTTPException(502, report["error"])
    return report


@app.get("/api/admin/metrics")
def metrics(user: User = Depends(admin), db: Session = Depends(get_db)):
    statuses = dict(db.execute(select(Run.status, func.count()).group_by(Run.status)).all())
    feedback_counts = dict(db.execute(select(Feedback.category, func.count()).group_by(Feedback.category)).all())
    runs = db.scalars(select(Run).where(Run.status == "completed")).all()
    durations = [(r.finished_at-r.created_at).total_seconds() for r in runs if r.finished_at]
    by_mode = mode_metrics(db.scalars(select(Run)).all(), db.scalars(select(Usage)).all())
    return {"runs": statuses, "feedback": feedback_counts, "llm_allowance": allowance_status(db),
        "by_mode": by_mode,
        "budgets": [{"day": b.day, "spent_rub": round(b.spent, 4)} for b in db.scalars(select(Budget).order_by(Budget.day.desc()).limit(7))],
        "latency_avg_seconds": round(sum(durations)/len(durations), 2) if durations else None,
        "insufficient_count": sum(r.result.get("verification") == "insufficient" for r in runs if r.result),
        "source_errors": db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "rss_error")),
        "source_errors_24h": db.scalar(select(func.count()).select_from(Audit).where(
            Audit.action == "rss_error", Audit.created_at >= utcnow() - timedelta(hours=24))),
        "documents": db.scalar(select(func.count()).select_from(Document)),
        "events": db.scalar(select(func.count()).select_from(Event)),
        "mode": "demo" if settings().demo_mode else "live",
        "quality_note": "Метрики релевантности и достоверности требуют независимой экспертной разметки; здесь они не заявляются."}
