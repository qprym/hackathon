"""Renewable ownership; a late worker cannot overwrite its replacement."""
import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session
from .config import settings
from .db import SessionLocal, utcnow

log=logging.getLogger(__name__)
_owner=ContextVar('job_owner',default=None)


class LeaseLost(RuntimeError):
    pass


def deadline():
    return utcnow()+timedelta(seconds=settings().job_lease_seconds)


@event.listens_for(Session,'before_flush')
def fence_writes(session,flush_context,instances):
    owner=_owner.get()
    if not owner:return
    model,key,token,lost=owner
    if not any(isinstance(row,model) and row.id==key for row in session.dirty):return
    if lost.is_set():raise LeaseLost('Владение задачей утрачено')
    stmt=select(model.lease_token,model.status,model.lease_until).where(model.id==key)
    if session.bind.dialect.name=='postgresql':stmt=stmt.with_for_update()
    row=session.connection().execute(stmt).first()
    if not row or row.lease_token!=token or row.status!='running' or not row.lease_until or row.lease_until<utcnow():
        raise LeaseLost('Другой worker восстановил задачу; прежний результат не опубликован')


def renew(model,key,token):
    with SessionLocal() as db:
        changed=db.execute(update(model).where(model.id==key,model.lease_token==token,
            model.status=='running',model.lease_until>=utcnow()).values(lease_until=deadline()))
        db.commit()
        return changed.rowcount==1


@contextmanager
def owned(model,key,token):
    stop=threading.Event();lost=threading.Event()
    def beat():
        while not stop.wait(max(1,settings().job_lease_seconds/3)):
            try:
                if not renew(model,key,token):lost.set();return
            except Exception:
                # A temporary DB failure cannot authorize publishing an expired lease.
                log.warning('Could not renew lease for %s',key)
    thread=threading.Thread(target=beat,name='job-heartbeat',daemon=True)
    context_token=_owner.set((model,key,token,lost));thread.start()
    try:yield
    finally:
        stop.set();thread.join(timeout=2);_owner.reset(context_token)
