import logging
import threading
from sqlalchemy import select, update
from .agent import run_agent
from .config import settings,settings_scope
from .db import SessionLocal, utcnow
from .llm import ModelUnavailable
from .models import Audit, Run, uid
from .leases import owned, deadline, LeaseLost

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
        .values(status="running", attempts=Run.attempts + 1, lease_until=deadline(),lease_token=uid()))
    db.commit()
    if changed.rowcount != 1:
        return None
    db.refresh(job)
    return job


@settings_scope()
def process_one():
    with SessionLocal() as db:
        run = claim_job(db)
        if not run:
            return False
        run_id, lease_token = run.id, run.lease_token
        try:
            expected=next((s['details'] for s in run.trace if s['step']=='Снимок конфигурации'),None)
            current={'mode':'demo' if settings().demo_mode else 'live','revision':settings().llm_model_revision,
                     'model':settings().llm_analysis_id,'provider':settings().llm_provider_mode}
            if expected and expected!=current:
                raise ModelUnavailable('Настройки модели изменились после создания задачи. Запустите новый разбор.')
            with owned(Run,run.id,run.lease_token):
                run_agent(db, run)
        except LeaseLost:
            db.rollback()
            log.warning('Worker no longer owns run %s',run.id)
        except Exception as exc:
            db.rollback()
            error = (str(exc) if isinstance(exc, ModelUnavailable) else
                         "Права доступа изменились. Запустите новый анализ из ленты." if isinstance(exc, PermissionError) else
                         "Ошибка обработки. Проверьте журнал worker.")
            # Failure publication needs the same fencing as successful publication.
            changed = db.execute(update(Run).where(Run.id == run_id, Run.lease_token == lease_token,
                Run.status == 'running', Run.lease_until >= utcnow()).values(status='failed',
                stage='Анализ не завершен', error=error, finished_at=utcnow(), lease_until=None))
            if changed.rowcount == 1:
                db.add(Audit(action="run_failed", actor="worker", details={"run_id": run_id, "error_type": type(exc).__name__}))
                db.commit()
                log.error("Run %s failed: %s", run_id, type(exc).__name__)
            else:
                db.rollback()
                log.warning('Failure from former owner ignored for run %s', run_id)
        return True


def work_loop(stop=None):
    stop = stop or threading.Event()
    from .feeds import feed_loop
    threading.Thread(target=feed_loop, args=(stop,), name="news-refresh", daemon=True).start()
    # Independent lanes prevent a long full-feed job from starving user analyses.
    def selection_loop():
        import time
        from .pipeline import schedule
        from .semantic_ranking import process_one as process_selection
        next_schedule=0
        while not stop.is_set():
            busy=False
            try:
                if time.monotonic()>=next_schedule:
                    schedule();next_schedule=time.monotonic()+settings().pipeline_interval_seconds
                if settings().neural_ranking_worker and not settings().demo_mode:
                    busy=process_selection()
            except Exception:log.exception('Selection iteration failed')
            stop.wait(.3 if busy else 1)
    threading.Thread(target=selection_loop,name='personalization',daemon=True).start()
    while not stop.is_set():
        try:
            busy = process_one()
        except Exception:
            log.exception("Worker iteration failed")
            busy = False
        stop.wait(.3 if busy else 1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    work_loop()
