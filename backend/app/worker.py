import logging
import threading
import time
from datetime import timedelta
from sqlalchemy import select, update
from .agent import run_agent
from .config import settings
from .db import SessionLocal, utcnow
from .llm import ModelUnavailable
from .models import Audit, Run

log = logging.getLogger(__name__)


def claim_job(db):
    now = utcnow()
    db.execute(update(Run).where(Run.status == "running", Run.lease_until < now, Run.attempts < 3)
               .values(status="queued", stage="Повтор после остановки", error="Задача восстановлена после остановки worker"))
    db.execute(update(Run).where(Run.status == "running", Run.lease_until < now, Run.attempts >= 3)
               .values(status="failed", stage="Ошибка", error="Превышено число восстановлений задачи", finished_at=now))
    db.commit()
    stmt = select(Run).where(Run.status == "queued").order_by(Run.created_at).limit(1)
    if db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    job = db.scalar(stmt)
    if not job:
        return None
    changed = db.execute(update(Run).where(Run.id == job.id, Run.status == "queued")
        .values(status="running", attempts=Run.attempts + 1, lease_until=now + timedelta(minutes=5)))
    db.commit()
    if changed.rowcount != 1:
        return None
    db.refresh(job)
    return job


def process_one():
    with SessionLocal() as db:
        run = claim_job(db)
        if not run:
            return False
        try:
            run_agent(db, run)
        except Exception as exc:
            db.rollback()
            run = db.get(Run, run.id)
            run.status, run.stage = "failed", "Анализ не завершен"
            run.error = str(exc) if isinstance(exc, ModelUnavailable) else "Ошибка обработки. Проверьте журнал worker."
            run.finished_at, run.lease_until = utcnow(), None
            db.add(Audit(action="run_failed", actor="worker", details={"run_id": run.id, "error_type": type(exc).__name__}))
            db.commit()
            log.error("Run %s failed: %s", run.id, type(exc).__name__)
        return True


def work_loop(stop=None):
    stop = stop or threading.Event()
    last_fetch = 0
    while not stop.is_set():
        try:
            busy = process_one()
            if settings().auto_fetch_rss and not busy and time.monotonic() - last_fetch > 1800:
                from .ingestion import FEEDS, import_feed
                for key in FEEDS:
                    with SessionLocal() as db:
                        try:
                            report = import_feed(db, key)
                            db.add(Audit(action="rss", actor="worker", details={"source": key, **report}))
                            db.commit()
                        except Exception as exc:
                            db.rollback()
                            db.add(Audit(action="rss_error", actor="worker", details={"source": key, "type": type(exc).__name__}))
                            db.commit()
                last_fetch = time.monotonic()
        except Exception:
            log.exception("Worker iteration failed")
            busy = False
        stop.wait(.3 if busy else 1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    work_loop()
