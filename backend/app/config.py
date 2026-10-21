from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


APPROVED_MODELS = {
    "Gemma 4 26B A4B", "GLM-5.3-Flash", "Qwen3.6 35B A3B",
    "DeepSeek-V4.1-Flash", "Qwen3-VL-30B-A3B-Instruct", "Kimi-K2.6",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./alfa.db"
    demo_mode: bool = True
    seed_demo: bool = True
    demo_password: str = "demo-alfa-2026"
    cookie_secure: bool = False
    inline_worker: bool = True
    auto_fetch_rss: bool = True
    rss_refresh_seconds: int = Field(default=1800, ge=60, le=86400)
    rss_item_limit: int = Field(default=50, ge=1, le=200)
    allowed_origins: str = "http://localhost:5173,http://localhost:8080"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_analysis_model: str = "Qwen3.6 35B A3B"
    llm_analysis_id: str = ""
    llm_extraction_model: str = "Gemma 4 26B A4B"
    llm_extraction_id: str = ""
    llm_input_rub_per_million: float = 0
    llm_output_rub_per_million: float = 0
    llm_daily_limit_rub: float = 450
    llm_budget_timezone: str = "Europe/Moscow"


@lru_cache
def settings():
    return Settings()
