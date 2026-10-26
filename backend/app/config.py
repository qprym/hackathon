from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Literal
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import hashlib
import json


APPROVED_MODELS = {
    "Gemma 4 26B A4B", "GLM-5.3-Flash", "Qwen3.6 35B A3B",
    "DeepSeek-V4.1-Flash", "Qwen3-VL-30B-A3B-Instruct", "Kimi-K2.6",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./alfa.db"
    demo_mode: bool = True
    preview_cached_only: bool = False
    seed_demo: bool = True
    demo_password: str = "demo-alfa-2026"
    cookie_secure: bool = False
    inline_worker: bool = True
    auto_fetch_rss: bool = True
    rss_refresh_seconds: int = Field(default=1800, ge=60, le=86400)
    rss_item_limit: int = Field(default=50, ge=1, le=200)
    allowed_origins: str = "http://localhost:5173,http://localhost:8080"
    llm_base_url: str = ""
    llm_provider_mode: Literal['remote','local'] = 'remote'
    llm_local_api_key: str = ""
    llm_local_max_tokens: int | None = Field(default=None,ge=1)
    llm_timeout_seconds: int = Field(default=180,ge=1)
    llm_api_key: str = ""
    llm_analysis_model: str = "Qwen3.6 35B A3B"
    llm_analysis_id: str = ""
    llm_extraction_model: str = "Gemma 4 26B A4B"
    llm_extraction_id: str = ""
    llm_input_rub_per_million: float = 0
    llm_output_rub_per_million: float = 0
    llm_daily_limit_rub: float = 450
    llm_request_limit: int = Field(default=20, ge=0)
    llm_test_limit_rub: float = Field(default=0, ge=0, le=500, allow_inf_nan=False)
    llm_budget_timezone: str = "Europe/Moscow"
    neural_ranking_worker: bool = False
    auto_personalization: bool = False
    active_company_ids: str = "U_26491,U_989,U_6923"
    pipeline_interval_seconds: int = Field(default=60, ge=5)
    llm_model_revision: str = ""
    # Technical envelope, including instructions/schema. Never truncate a source to fit.
    llm_context_characters: int = Field(default=120000, ge=4000)
    job_lease_seconds: int = Field(default=90, ge=10)
    llm_settings_path: str = '.runtime/llm.json'


@lru_cache
def environment_settings():
    return Settings()


RUNTIME_FIELDS = frozenset({
    'demo_mode','preview_cached_only','neural_ranking_worker','auto_personalization','active_company_ids',
    'llm_base_url','llm_provider_mode','llm_api_key','llm_local_api_key','llm_analysis_model','llm_analysis_id',
    'llm_extraction_model','llm_extraction_id','llm_timeout_seconds','llm_context_characters','llm_model_revision',
    'llm_input_rub_per_million','llm_output_rub_per_million','llm_daily_limit_rub','llm_request_limit','llm_test_limit_rub',
})
_pinned = ContextVar('llm_settings_snapshot', default=None)

class SettingsUnavailable(RuntimeError):
    pass


def runtime_document():
    try:
        raw=Path(environment_settings().llm_settings_path).read_text(encoding='utf8')
    except FileNotFoundError:return None
    except OSError:raise SettingsUnavailable('Не удалось прочитать настройки LLM.') from None
    try:
        doc=json.loads(raw)
        if doc.get('version')!=1 or not isinstance(doc.get('revision'),str) or not isinstance(doc.get('overrides'),dict):
            raise ValueError()
        if set(doc['overrides'])-RUNTIME_FIELDS:raise ValueError()
        return doc
    except (ValueError,TypeError,AttributeError):
        raise SettingsUnavailable('Сохранённые настройки LLM повреждены; требуется восстановить файл настроек.') from None


@lru_cache(maxsize=4)
def _resolved(base_json,document_json):
    try:
        cfg=Settings.model_validate(json.loads(base_json) | json.loads(document_json)['overrides'])
    except ValueError:
        raise SettingsUnavailable('Сохранённые настройки LLM не прошли проверку.') from None
    if not cfg.demo_mode:
        identity=[cfg.llm_provider_mode,cfg.llm_base_url,cfg.llm_analysis_model,cfg.llm_analysis_id,
                  cfg.llm_extraction_model,cfg.llm_extraction_id,cfg.llm_model_revision]
        cfg.llm_model_revision='connection-'+hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:20]
    return cfg


def settings():
    pinned=_pinned.get()
    if pinned is not None:return pinned
    base=environment_settings();doc=runtime_document()
    return _resolved(base.model_dump_json(),json.dumps(doc,sort_keys=True)) if doc else base


@contextmanager
def settings_scope():
    # An in-flight analysis uses one endpoint, credential and tariff snapshot throughout.
    token=_pinned.set(settings().model_copy(deep=True))
    try:yield
    finally:_pinned.reset(token)
