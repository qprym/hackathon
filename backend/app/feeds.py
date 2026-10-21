"""Persistent schedules and leases for public news imports."""
import logging
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .config import settings
from .db import SessionLocal, utcnow
from .ingestion import FEEDS, FEED_NAMES, import_feed
from .models import Audit, FeedState, uid

log = logging.getLogger(__name__)


def refresh_feed(key, *, force=False, actor="worker"):
    if key not in FEEDS:
        raise ValueError("Неизвестный источник")
    with SessionLocal() as db:
        now, token = utcnow(), uid()
        insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
        db.execute(insert(FeedState).values(key=key, status="idle", report={})
                   .on_conflict_do_nothing(index_elements=["key"]))
        claim = update(FeedState).where(FeedState.key == key,
            or_(FeedState.lease_until.is_(None), FeedState.lease_until < now))
        if not force:
            claim = claim.where(or_(FeedState.status == "running",
                FeedState.next_refresh_at.is_(None), FeedState.next_refresh_at <= now))
        claimed = db.execute(claim.values(status="running", lease_token=token,
            lease_until=now + timedelta(minutes=5), last_started_at=now, error=None))
        db.commit()
        if claimed.rowcount != 1:
            state = db.get(FeedState, key)
            return {"status": state.status, "skipped": True,
                    "message": "Обновление уже выполняется или еще не наступило время следующего запуска"}

        def heartbeat():
            result = db.execute(update(FeedState).where(FeedState.key == key, FeedState.lease_token == token)
                .values(lease_until=utcnow() + timedelta(minutes=5)))
            db.commit()
            if result.rowcount != 1:
                raise RuntimeError("Source import lease lost")

        try:
            report = import_feed(db, key, on_progress=heartbeat)
            status = "partial" if report["errors"] or report["warnings"] else "ok"
            error = None
            delay = settings().rss_refresh_seconds
        except Exception as exc:
            db.rollback()
            status, error = "error", "Не удалось загрузить источник. Повторная попытка запланирована."
            report = {"imported": 0, "error_type": type(exc).__name__}
            delay = min(settings().rss_refresh_seconds, 300)
            log.warning("Feed %s failed: %s", key, type(exc).__name__)
        finished = utcnow()
        updated = db.execute(update(FeedState).where(FeedState.key == key, FeedState.lease_token == token)
            .values(status=status, report=report, error=error, last_finished_at=finished,
                    next_refresh_at=finished + timedelta(seconds=delay), lease_token=None, lease_until=None))
        if updated.rowcount:
            db.add(Audit(action="rss_error" if status == "error" else "rss", actor=actor,
                         details={"source": key, "status": status, **report}))
        db.commit()
        return {"status": status, **report, **({"error": error} if error else {})}


def feed_status(db):
    states = {state.key: state for state in db.scalars(select(FeedState)).all()}
    iso = lambda value: value.isoformat() + "Z" if value else None
    items = []
    for key, name in FEED_NAMES.items():
        state = states.get(key)
        status = state.status if state else "pending"
        if state and status == "running" and state.lease_until and state.lease_until < utcnow():
            status = "recovering"
        items.append({"key": key, "name": name, "status": status,
            "last_started_at": iso(state.last_started_at) if state else None,
            "last_finished_at": iso(state.last_finished_at) if state else None,
            "next_refresh_at": iso(state.next_refresh_at) if state else None,
            "report": state.report if state else {}, "error": state.error if state else None})
    return {"automatic": settings().auto_fetch_rss, "interval_seconds": settings().rss_refresh_seconds, "items": items}


def feed_loop(stop):
    while not stop.is_set():
        for key in FEEDS:
            if stop.is_set():
                return
            try:
                refresh_feed(key)
            except Exception:
                log.exception("Feed scheduler failed for %s", key)
        stop.wait(10)
