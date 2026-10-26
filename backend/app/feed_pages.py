"""Stable, user-bound pagination. No model calls on reads."""
from datetime import timedelta
from sqlalchemy import delete
from fastapi import HTTPException
from .db import utcnow
from .models import FeedSnapshot
from .semantic_ranking import fingerprint


def read(db,user,company_id,context,query,version,offset,limit):
    row=db.get(FeedSnapshot,version)
    if not row or row.user_id!=user.id or row.company_id!=company_id:
        raise HTTPException(404,'Подборка не найдена')
    if row.expires_at<utcnow() or row.context_key!=fingerprint(context) or row.query_key!=fingerprint(query):
        raise HTTPException(409,'Подборка устарела или изменились фильтры. Обновите ленту.')
    return page(row.payload,version,offset,limit)


def page(payload,version,offset,limit):
    items=payload['items'];end=offset+limit
    return {**payload,'items':items[offset:end],'feed_version':version,'total':len(items),
            'offset':offset,'next_offset':end if end<len(items) else None}


def save(db,user,company_id,context,query,payload,offset,limit):
    version=fingerprint([user.id,company_id,context,query,payload])
    if not db.get(FeedSnapshot,version):
        db.execute(delete(FeedSnapshot).where(FeedSnapshot.expires_at<utcnow()))
        db.add(FeedSnapshot(id=version,user_id=user.id,company_id=company_id,context_key=fingerprint(context),
            query_key=fingerprint(query),payload=payload,expires_at=utcnow()+timedelta(hours=24)))
        try:db.commit()
        except Exception:
            db.rollback()
            if not db.get(FeedSnapshot,version):raise
    return page(payload,version,offset,limit)
