"""Admin-managed server-side credentials. No provider requests on save or read."""
import json
import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field,SecretStr
from typing import Literal
from sqlalchemy import select,func,or_
from .config import APPROVED_MODELS,Settings,environment_settings,runtime_document,RUNTIME_FIELDS,LLM_FIELDS,settings
from .llm import local_endpoint
from .models import Audit,Run,RankingJob,FeedState,RelevanceAssessment
from .db import utcnow

_write_lock=threading.RLock()


class ConnectionInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    revision: str
    enabled: bool=False
    provider_mode: Literal['local','remote']='remote'
    base_url: str=Field(default='',max_length=1000)
    api_key: SecretStr | None=None
    clear_api_key: bool=False
    analysis_model: str
    analysis_id: str=Field(default='',max_length=150)
    extraction_model: str
    extraction_id: str=Field(default='',max_length=150)
    model_revision: str=Field(default='',max_length=100)
    timeout_seconds: int=Field(default=180,ge=1,le=3600)
    context_characters: int=Field(default=120000,ge=4000,le=10000000)
    automatic: bool=False
    active_company_ids: str=Field(default='U_26491,U_989,U_6923',max_length=4000)
    input_rub_per_million: float=Field(default=0,ge=0)
    output_rub_per_million: float=Field(default=0,ge=0)
    daily_limit_rub: float=Field(default=450,ge=0,le=500)
    test_limit_rub: float=Field(default=0,ge=0,le=500)
    request_limit: int=Field(default=20,ge=0)


def raw_settings(doc):
    return Settings.model_validate(environment_settings().model_dump() | (doc['overrides'] if doc else {}))


def public_settings():
    doc=runtime_document();cfg=raw_settings(doc)
    return {'revision':doc['revision'] if doc else 'environment','source':'interface' if doc and set(doc['overrides']) & LLM_FIELDS else 'environment',
        'enabled':not cfg.demo_mode,'provider_mode':cfg.llm_provider_mode,'base_url':cfg.llm_base_url,
        'api_key_configured':bool(cfg.llm_api_key if cfg.llm_provider_mode=='remote' else cfg.llm_local_api_key),
        'analysis_model':cfg.llm_analysis_model,'analysis_id':cfg.llm_analysis_id,
        'extraction_model':cfg.llm_extraction_model,'extraction_id':cfg.llm_extraction_id,
        'model_revision':cfg.llm_model_revision,'timeout_seconds':cfg.llm_timeout_seconds,
        'context_characters':cfg.llm_context_characters,'automatic':cfg.auto_personalization,
        'active_company_ids':cfg.active_company_ids,'input_rub_per_million':cfg.llm_input_rub_per_million,
        'output_rub_per_million':cfg.llm_output_rub_per_million,'daily_limit_rub':cfg.llm_daily_limit_rub,
        'test_limit_rub':cfg.llm_test_limit_rub,'request_limit':cfg.llm_request_limit,
        'approved_models':sorted(APPROVED_MODELS)}


def ensure_idle(db):
    running=db.scalar(select(func.count()).select_from(Run).where(Run.status.in_(['queued','running'])))
    selecting=db.scalar(select(func.count()).select_from(RankingJob).where(RankingJob.status.in_(['queued','running'])))
    if running or selecting:raise HTTPException(409,'Дождитесь завершения очереди анализов и отбора перед сменой подключения.')


def save_settings(db,user,body):
    with _write_lock:
        old=runtime_document();revision=old['revision'] if old else 'environment'
        if body.revision!=revision:raise HTTPException(409,'Настройки изменены в другом окне. Обновите страницу.')
        ensure_idle(db)
        cfg=raw_settings(old);url=body.base_url.strip().rstrip('/')
        if url.endswith('/chat/completions'):url=url[:-len('/chat/completions')]
        try:parsed=urlsplit(url);parsed.port
        except ValueError:raise HTTPException(422,'Проверьте адрес API.') from None
        if url and (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(c.isspace() for c in url)):
            raise HTTPException(422,'Адрес API не должен содержать логин, пароль, параметры или фрагмент.')
        if url and (body.provider_mode=='remote' and parsed.scheme!='https' or body.provider_mode=='local' and not local_endpoint(url)):
            raise HTTPException(422,'Для удалённого API нужен HTTPS; для локального — адрес локального сервера.')
        if body.analysis_model not in APPROVED_MODELS or body.extraction_model not in APPROVED_MODELS:
            raise HTTPException(422,'Выберите модель из разрешённого списка.')
        key=(body.api_key.get_secret_value().strip() if body.api_key else '')
        if len(key)>4096 or any(c in key for c in ('\r','\n','\x00')):
            raise HTTPException(422,'Проверьте формат токена API.')
        # Never forward a stored token to a changed endpoint or a different provider mode.
        same_target=body.provider_mode==cfg.llm_provider_mode and url==cfg.llm_base_url.rstrip('/')
        if not key and same_target:key=cfg.llm_api_key if body.provider_mode=='remote' else cfg.llm_local_api_key
        if body.clear_api_key:key=''
        if body.enabled:
            if not url or not body.analysis_id.strip() or not body.extraction_id.strip():
                raise HTTPException(422,'Для включения заполните адрес API и ID моделей.')
            if body.provider_mode=='remote' and (not key or body.input_rub_per_million<=0 or body.output_rub_per_million<=0 or body.test_limit_rub<=0 or body.request_limit<=0 or body.daily_limit_rub<=0):
                raise HTTPException(422,'Для удалённого API нужны токен, тарифы и ненулевые лимиты теста.')
            if parsed.hostname=='api.deepseek.com' and (body.analysis_model!='DeepSeek-V4.1-Flash' or body.extraction_model!='DeepSeek-V4.1-Flash' or body.analysis_id!='deepseek-flash' or body.extraction_id!='deepseek-flash'):
                raise HTTPException(422,'Для DeepSeek выберите DeepSeek-V4.1-Flash с ID deepseek-flash.')
        if body.automatic and not body.enabled:raise HTTPException(422,'Для автоматической обработки включите вызовы LLM.')
        started=cfg.auto_personalization_started_at
        if body.automatic and (not cfg.auto_personalization or not same_target or not started):
            started=utcnow().isoformat()
        fields={'demo_mode':not body.enabled,'preview_cached_only':not body.enabled,
            'neural_ranking_worker':body.enabled,'auto_personalization':body.enabled and body.automatic,
            'auto_personalization_started_at':started,
            'llm_provider_mode':body.provider_mode,'llm_base_url':url,
            'llm_api_key':key if body.provider_mode=='remote' else '',
            'llm_local_api_key':key if body.provider_mode=='local' else '',
            'llm_analysis_model':body.analysis_model,'llm_analysis_id':body.analysis_id.strip(),
            'llm_extraction_model':body.extraction_model,'llm_extraction_id':body.extraction_id.strip(),
            'llm_model_revision':body.model_revision,'llm_timeout_seconds':body.timeout_seconds,
            'llm_context_characters':body.context_characters,'active_company_ids':body.active_company_ids,
            **{'llm_'+k:getattr(body,k) for k in ('input_rub_per_million','output_rub_per_million','daily_limit_rub','test_limit_rub','request_limit')}}
        assert set(fields)<=RUNTIME_FIELDS
        write_runtime((old['overrides'] if old else {}) | fields)
        from .llm import PROVIDER_BLOCK_KEY
        block=db.get(FeedState,PROVIDER_BLOCK_KEY)
        if block:
            block.status='idle';block.error=None
        if body.enabled and body.automatic and same_target and cfg.auto_personalization_started_at and all(
            getattr(body,key)==getattr(cfg,'llm_'+key) for key in ('analysis_model','analysis_id','extraction_model','extraction_id','model_revision')):
            from datetime import datetime
            # An explicit save can resume payment/quota-blocked work from this activation window.
            for job in db.scalars(select(RankingJob).where(RankingJob.status=='failed',or_(RankingJob.error.contains('HTTP 402'),
                RankingJob.error.contains('денежный лимит'),RankingJob.error.contains('Дневной бюджет')),
                or_(RankingJob.payload['purpose'].as_string().is_(None),RankingJob.payload['purpose'].as_string()=='selection_review'),
                RankingJob.company_id.in_([x.strip() for x in body.active_company_ids.split(',') if x.strip()]),
                RankingJob.created_at>=datetime.fromisoformat(cfg.auto_personalization_started_at))):
                if job.payload.get('purpose')=='selection_review':
                    active=settings()
                    retry=RankingJob(user_id=job.user_id,company_id=job.company_id,cache_keys=job.cache_keys,
                        payload={'purpose':'resume_selection_review','context':job.payload['context'],
                            'provider_mode':active.llm_provider_mode,'model_revision':active.llm_model_revision},status='queued')
                    db.add(retry);db.flush();job.status='superseded'
                    job.response={**(job.response or {}),'resumed_by':retry.id}
                    continue
                job.status='queued';job.error=None;job.finished_at=None
                for row in db.scalars(select(RelevanceAssessment).where(RelevanceAssessment.job_id==job.id)):
                    row.status='queued';row.error=None
        # Neither request bodies nor credentials enter the audit log.
        db.add(Audit(action='llm_settings_updated',actor=user.id,details={'enabled':body.enabled,
            'provider_mode':body.provider_mode,'credential_changed':bool(body.api_key) or body.clear_api_key,'provider_called':False}))
        db.commit()
        return public_settings()


def reset_settings(db,user,revision):
    with _write_lock:
        doc=runtime_document()
        if revision!=(doc['revision'] if doc else 'environment'):raise HTTPException(409,'Настройки изменены. Обновите страницу.')
        ensure_idle(db)
        write_runtime({k:v for k,v in (doc['overrides'] if doc else {}).items() if k not in LLM_FIELDS})
        db.add(Audit(action='llm_settings_reset',actor=user.id,details={'provider_called':False}));db.commit()
        return public_settings()


def write_runtime(fields):
    """Caller holds _write_lock; preserve unrelated sections before passing overrides."""
    assert set(fields)<=RUNTIME_FIELDS
    path=Path(environment_settings().llm_settings_path)
    if not fields:
        path.unlink(missing_ok=True);return
    path.parent.mkdir(parents=True,exist_ok=True);name=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=path.parent,prefix='.settings-',delete=False) as handle:
            name=handle.name;os.chmod(name,0o600)
            json.dump({'version':1,'revision':str(uuid4()),'overrides':fields},handle,ensure_ascii=False)
            handle.flush();os.fsync(handle.fileno())
        os.replace(name,path);name=None
    finally:
        if name:Path(name).unlink(missing_ok=True)
