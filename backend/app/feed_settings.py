"""Administrator-controlled schedules for the registered public news sources."""
from datetime import timedelta
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from .config import runtime_document
from .db import utcnow
from .ingestion import FEEDS,FEED_NAMES
from .llm_settings import _write_lock,raw_settings,write_runtime
from .models import Audit,FeedState


class FeedSettingsInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:str=Field(max_length=100)
    automatic:bool
    interval_seconds:int=Field(ge=60,le=86400)
    sources:list[Literal['cbr','vedomosti']]=Field(max_length=2)


def public_settings():
    doc=runtime_document();cfg=raw_settings(doc)
    return {'revision':doc['revision'] if doc else 'environment','automatic':cfg.auto_fetch_rss,
            'interval_seconds':cfg.rss_refresh_seconds,'sources':cfg.rss_sources,
            'catalog':[{'key':key,'name':FEED_NAMES[key],'url':url} for key,url in FEEDS.items()]}


def save_settings(db,user,body):
    with _write_lock:
        doc=runtime_document()
        if body.revision!=(doc['revision'] if doc else 'environment'):
            raise HTTPException(409,'Настройки изменились в другом окне. Обновите страницу.')
        if body.automatic and not body.sources:raise HTTPException(422,'Выберите хотя бы один источник для автообновления.')
        previous=raw_settings(doc);sources=list(dict.fromkeys(body.sources))
        values={'auto_fetch_rss':body.automatic,'rss_refresh_seconds':body.interval_seconds,'rss_sources':sources}
        write_runtime((doc['overrides'] if doc else {}) | values)
        now=utcnow()
        if body.automatic:
            for state in db.scalars(select(FeedState).where(FeedState.key.in_(sources))):
                if state.status=='running':continue
                state.next_refresh_at=(now if not previous.auto_fetch_rss or state.key not in previous.rss_sources
                    else max(now,state.last_finished_at+timedelta(seconds=body.interval_seconds)) if state.last_finished_at else now)
        db.add(Audit(action='feed_settings_updated',actor=user.id,details={**values,'provider_called':False}))
        db.commit()
        return public_settings()
