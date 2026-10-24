import hashlib
import json
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from .auth import admin, authorize_company, current_user, make_session, token_hash, verify_password
from .config import settings
from .context import company_context
from .db import SessionLocal, engine, get_db, initialize_development_schema, utcnow
from .ingestion import FEEDS, extract_pdf, import_csv, import_document
from .models import Audit, AuthSession, Budget, Company, Document, Event, Feedback, Link, Run, Usage, User
from .retrieval import TOPIC_NAMES, rank_event, search_documents
from .bank_relevance import SEARCH_VERSION
from .schemas import Analyze, FeedbackInput, Login, NewsInput, Question, Role
from .seed import seed
from .worker import work_loop
from .feeds import feed_status, refresh_feed
from .llm import allowance_status
from .cashflow import VALIDATION_VERSION


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


app = FastAPI(title="Альфа · Контекст", version="0.1.0", lifespan=lifespan)
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
    return [{"id": c.id, "name": c.name, "industry": c.industry, "region": c.region, "synthetic": c.synthetic}
            for c in db.scalars(select(Company).where(Company.id.in_(user.company_ids))).all()]


@app.get("/api/companies/{company_id}/context")
def context(company_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    company = authorize_company(db, user, company_id)
    return company_context(db, company, user.company_ids)


@app.get("/api/feed")
def feed(company_id: str, role: Role = "CFO", topic: str | None = None, corpus: Literal["real", "synthetic"] = "real",
         q: str = "",
         user: User = Depends(current_user), db: Session = Depends(get_db)):
    company = authorize_company(db, user, company_id)
    ctx = company_context(db, company, user.company_ids)
    if corpus == "synthetic" and not company.synthetic:
        raise HTTPException(422, "Учебные события доступны только для учебных профилей")
    stmt = select(Event).where(Event.synthetic == (corpus == "synthetic"))
    if q.strip():
        stmt = stmt.where(Event.title.icontains(q.strip()[:200], autoescape=True))
    events = db.scalars(stmt.order_by(Event.published_at.desc()).limit(500)).all()
    entries = []
    for event in events:
        if topic and topic not in event.topics:
            continue
        doc = db.get(Document, event.document_ids[0]) if event.document_ids else None
        ranking = rank_event(event, ctx, role)
        entries.append({"id": event.id, "title": event.title, "topics": event.topics,
            "published_at": event.published_at.isoformat() + "Z", "synthetic": event.synthetic,
            "summary": doc.content[:230] if doc else "", "publisher": doc.publisher if doc else "",
            "source_count": len(event.document_ids), **ranking})
    entries.sort(key=lambda item: (item["score"], item["published_at"]), reverse=True)
    return {"items": entries[:50], "topics": TOPIC_NAMES, "company_id": company_id, "role": role, "corpus": corpus}


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
    documents = db.execute(select(Document.id, Document.content_hash).where(Document.synthetic == event.synthetic)
                           .order_by(Document.id)).all()
    context_version = company_context(db, company, user.company_ids)
    access_scope = sorted(set(user.company_ids))
    key = hashlib.sha256(json.dumps([user.id, access_scope, body.model_dump(), company.features, str(company.updated_at),
        [list(d) for d in documents], context_version, question, parent if question else None, settings().demo_mode,
        settings().llm_analysis_id, settings().llm_extraction_id, "prompt-v18", SEARCH_VERSION, VALIDATION_VERSION], sort_keys=True, default=str).encode()).hexdigest()
    existing = db.scalar(select(Run).where(Run.cache_key == key, Run.status.in_(["queued", "running", "completed"])).order_by(Run.created_at.desc()))
    if existing and not (parent and not question and existing.status == 'completed' and (existing.result or {}).get('verification') == 'insufficient'):
        return {"run_id": existing.id, "cached": existing.status == "completed"}
    if not settings().demo_mode and (question or not parent) and allowance_status(db)['requests_remaining'] < 5:
        raise HTTPException(429, 'Для нового разбора или вопроса нужны как минимум пять обращений. Оставшаяся квота сохранена; готовые результаты доступны из кеша.')
    pending = db.scalar(select(func.count()).select_from(Run).where(Run.user_id == user.id, Run.status.in_(["queued", "running"])))
    if pending >= 5:
        raise HTTPException(429, "Дождитесь завершения текущих анализов")
    run = Run(user_id=user.id, company_id=company.id, event_id=event.id, role=body.role,
              question=question, parent_id=parent, cache_key=key, access_scope=access_scope)
    if single_pass:
        run.trace = [{'step': 'Режим пересчёта', 'at': utcnow().isoformat() + 'Z', 'details': {'max_attempts': 1,
            'note': 'Свежий поиск, один синтез и независимая проверка; максимум два обращения без платных повторов.'}}]
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
    steps = [{**s, "details": {k: v for k, v in s["details"].items() if k != "counterparties"}} for s in run.trace]
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
    if not settings().demo_mode and allowance_status(db)['requests_remaining'] < 4:
        raise HTTPException(429, 'Для исправления с корректирующим циклом нужны четыре оставшихся обращения. Общий лимит не увеличен.')
    return create_run(db, user, Analyze(company_id=run.company_id, event_id=run.event_id, role=run.role), parent=run.id)


@app.post('/api/insights/{run_id}/refresh', status_code=202)
def refresh_insight(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run = authorized_run(db, user, run_id)
    if (run.status != 'completed' or (run.result or {}).get('verification') != 'checked'
            or (run.result.get('search_version') == SEARCH_VERSION and run.result.get('validation_version') == VALIDATION_VERSION)):
        raise HTTPException(409, 'Пересчёт доступен для проверенного разбора с прежней версией поиска или проверки')
    if not settings().demo_mode and allowance_status(db)['requests_remaining'] < 2:
        raise HTTPException(429, 'Для пересчёта и независимой проверки нужны два оставшихся обращения.')
    return create_run(db, user, Analyze(company_id=run.company_id, event_id=run.event_id, role=run.role),
                      parent=run.id, single_pass=True)


@app.get("/api/sources/{source_id}")
def source(source_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = db.get(Document, source_id)
    if not doc:
        raise HTTPException(404, "Источник не найден")
    return {"id": doc.id, "title": doc.title, "kind": doc.kind, "publisher": doc.publisher,
            "url": doc.url, "published_at": doc.published_at.isoformat() + "Z", "content": doc.content,
            "chunks": doc.chunks, "synthetic": doc.synthetic, "ingestion": doc.ingestion_meta}


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
                "coverage": "provided", "extraction": "ocr" if any(c.get('extraction') == 'ocr' for c in chunks) else "pdf",
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
    return {"runs": statuses, "feedback": feedback_counts, "llm_allowance": allowance_status(db),
        "budgets": [{"day": b.day, "spent_rub": round(b.spent, 4)} for b in db.scalars(select(Budget).order_by(Budget.day.desc()).limit(7))],
        "latency_avg_seconds": round(sum(durations)/len(durations), 2) if durations else None,
        "insufficient_count": sum(r.result.get("verification") == "insufficient" for r in runs if r.result),
        "source_errors": db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "rss_error")),
        "documents": db.scalar(select(func.count()).select_from(Document)),
        "events": db.scalar(select(func.count()).select_from(Event)),
        "mode": "demo" if settings().demo_mode else "live",
        "quality_note": "Метрики релевантности и достоверности требуют независимой экспертной разметки; здесь они не заявляются."}
