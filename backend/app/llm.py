"""The only LLM gateway. Prices/IDs are explicit organizer configuration, never guessed."""
import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from .config import APPROVED_MODELS, settings
from .db import SessionLocal
from .models import Budget, Usage


class ModelUnavailable(RuntimeError):
    pass


class BudgetExceeded(ModelUnavailable):
    pass


def reserve_budget(amount):
    cfg = settings()
    day = datetime.now(ZoneInfo(cfg.llm_budget_timezone)).date().isoformat()
    limit = min(max(cfg.llm_daily_limit_rub, 0), 500)
    with SessionLocal() as db:
        insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
        db.execute(insert(Budget).values(day=day, spent=0).on_conflict_do_nothing(index_elements=["day"]))
        updated = db.execute(update(Budget).where(Budget.day == day, Budget.spent + amount <= limit)
                             .values(spent=Budget.spent + amount))
        if updated.rowcount != 1:
            db.rollback()
            raise BudgetExceeded("Дневной бюджет приложения исчерпан. Новые вызовы остановлены.")
        db.commit()
    return day


def complete_json(system, payload, *, run_id=None, extraction=False, max_tokens=2400):
    cfg = settings()
    if cfg.demo_mode:
        raise ModelUnavailable("LLM отключена в демонстрационном режиме")
    model = cfg.llm_extraction_model if extraction else cfg.llm_analysis_model
    model_id = cfg.llm_extraction_id if extraction else cfg.llm_analysis_id
    if model not in APPROVED_MODELS:
        raise ModelUnavailable("Модель отсутствует в разрешенном списке кейса")
    if not cfg.llm_base_url.startswith("https://") or not cfg.llm_api_key or not model_id:
        raise ModelUnavailable("Не настроены HTTPS API, ключ или идентификатор разрешенной модели")
    if cfg.llm_input_rub_per_million <= 0 or cfg.llm_output_rub_per_million <= 0:
        raise ModelUnavailable("Для контроля бюджета укажите подтвержденные тарифы провайдера")
    content = json.dumps(payload, ensure_ascii=False, default=str)
    # UTF-8 byte count is a conservative input token ceiling for BPE models.
    input_ceiling = len((system + content).encode("utf-8")) + 512
    reservation = (input_ceiling * cfg.llm_input_rub_per_million + max_tokens * cfg.llm_output_rub_per_million) / 1_000_000
    day = reserve_budget(reservation)
    usage = None
    try:
        response = httpx.post(cfg.llm_base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {cfg.llm_api_key}"}, timeout=75,
            json={"model": model_id, "messages": [{"role": "system", "content": system},
                  {"role": "user", "content": content}], "temperature": .1,
                  "max_tokens": max_tokens, "response_format": {"type": "json_object"}})
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage")
        answer = body["choices"][0]["message"]["content"]
        if not isinstance(answer, str):
            raise ValueError("Ответ модели не является текстом JSON")
        result = json.loads(answer)
        if not isinstance(result, dict):
            raise ValueError("Ответ модели должен быть объектом JSON")
        status = "ok"
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        # A timeout may still be billed. Do not refund unknown usage or retry blindly.
        status = "error"
        result = None
        error = ModelUnavailable("Провайдер LLM недоступен или вернул некорректный JSON. Проверьте конфигурацию и журнал расходов.")
    finally:
        valid_usage = isinstance(usage, dict) and all(isinstance(usage.get(k), int) and usage[k] >= 0 for k in ("prompt_tokens", "completion_tokens"))
        actual = reservation
        if valid_usage:
            actual = (usage["prompt_tokens"] * cfg.llm_input_rub_per_million + usage["completion_tokens"] * cfg.llm_output_rub_per_million) / 1_000_000
        with SessionLocal() as db:
            db.execute(update(Budget).where(Budget.day == day).values(spent=Budget.spent + actual - reservation))
            db.add(Usage(run_id=run_id, model=model, input_tokens=usage["prompt_tokens"] if valid_usage else 0,
                         output_tokens=usage["completion_tokens"] if valid_usage else 0,
                         cost_rub=actual, status=status if valid_usage else status + "_reserved"))
            db.commit()
    if result is None:
        raise error
    return result
