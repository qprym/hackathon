"""The only LLM gateway. Prices/IDs are explicit organizer configuration, never guessed."""
import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from .config import APPROVED_MODELS, MAX_TRIAL_REQUESTS, settings
from .db import SessionLocal
from .models import Budget, LlmAllowance, Usage

ALLOWANCE_KEY = "initial-trial"


class ModelUnavailable(RuntimeError):
    pass


class BudgetExceeded(ModelUnavailable):
    pass


class OutputTruncated(ValueError):
    pass


def allowance_status(db):
    cfg = settings()
    allowance = db.get(LlmAllowance, ALLOWANCE_KEY)
    used = allowance.requests if allowance else 0
    limit = min(cfg.llm_request_limit, MAX_TRIAL_REQUESTS)
    return {"request_limit": limit, "requests_used": used, "requests_remaining": max(limit - used, 0),
            "spent_rub": round(allowance.spent, 6) if allowance else 0,
            "test_limit_rub": cfg.llm_test_limit_rub}


def reserve_budget(amount, *, count_request=False):
    if not math.isfinite(amount) or amount < 0:
        raise BudgetExceeded("Не удалось определить верхнюю оценку стоимости запроса")
    cfg = settings()
    day = datetime.now(ZoneInfo(cfg.llm_budget_timezone)).date().isoformat()
    limit = min(max(cfg.llm_daily_limit_rub, 0), 500)
    with SessionLocal() as db:
        insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
        if count_request:
            if cfg.llm_test_limit_rub <= 0:
                raise BudgetExceeded("Укажите общий денежный лимит теста LLM_TEST_LIMIT_RUB. Вызов не выполнен.")
            db.execute(insert(LlmAllowance).values(key=ALLOWANCE_KEY, requests=0, spent=0)
                       .on_conflict_do_nothing(index_elements=["key"]))
            reserved = db.execute(update(LlmAllowance).where(LlmAllowance.key == ALLOWANCE_KEY,
                LlmAllowance.requests < min(cfg.llm_request_limit, MAX_TRIAL_REQUESTS),
                LlmAllowance.spent + amount <= cfg.llm_test_limit_rub)
                .values(requests=LlmAllowance.requests + 1, spent=LlmAllowance.spent + amount))
            if reserved.rowcount != 1:
                db.rollback()
                raise BudgetExceeded("Общий лимит запросов или денежный лимит теста исчерпан. Новые вызовы остановлены.")
        db.execute(insert(Budget).values(day=day, spent=0).on_conflict_do_nothing(index_elements=["day"]))
        updated = db.execute(update(Budget).where(Budget.day == day, Budget.spent + amount <= limit)
                             .values(spent=Budget.spent + amount))
        if updated.rowcount != 1:
            db.rollback()
            raise BudgetExceeded("Дневной бюджет приложения исчерпан. Новые вызовы остановлены.")
        db.commit()
    return day


def affordable_review_tokens(system, payload, *, preferred=8000, minimum=6000):
    """Read-only preflight. The gateway still reserves the exact ceiling atomically."""
    cfg = settings()
    content = json.dumps(payload, ensure_ascii=False, default=str)
    input_cost = (len((system + content).encode('utf-8')) + 512) * cfg.llm_input_rub_per_million / 1_000_000
    day = datetime.now(ZoneInfo(cfg.llm_budget_timezone)).date().isoformat()
    with SessionLocal() as db:
        allowance = db.get(LlmAllowance, ALLOWANCE_KEY)
        daily = db.get(Budget, day)
        remaining = min(cfg.llm_test_limit_rub - (allowance.spent if allowance else 0),
                        min(cfg.llm_daily_limit_rub, 500) - (daily.spent if daily else 0))
    if cfg.llm_output_rub_per_million <= 0:
        raise BudgetExceeded('Для проверки не настроены тарифы провайдера.')
    limit = min(preferred, math.floor((remaining - input_cost) * 1_000_000 / cfg.llm_output_rub_per_million))
    if limit < minimum:
        raise BudgetExceeded('Остатка бюджета недостаточно для полной проверки: нужны входной пакет и минимум '
                             f'{minimum} выходных токенов. Проверка не вызывалась, черновик не принят.')
    return limit


def complete_json(system, payload, *, run_id=None, extraction=False, max_tokens=2400, reasoning=False):
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
    request_body = {"model": model_id, "messages": [{"role": "system", "content": system},
        {"role": "user", "content": content}],
        "temperature": .1, "max_tokens": max_tokens, "response_format": {"type": "json_object"}}
    if urlsplit(cfg.llm_base_url).hostname == 'api.deepseek.com':
        if model != 'DeepSeek-V4.1-Flash' or model_id != 'deepseek-flash':
            raise ModelUnavailable('Для прямого API DeepSeek разрешён только deepseek-flash (DeepSeek-V4.1-Flash)')
        # Spend reasoning tokens only on synthesis and verification, within the same output cap.
        request_body['thinking'] = {'type': 'enabled' if reasoning else 'disabled'}
        if reasoning:
            request_body['reasoning_effort'] = 'high'
            request_body.pop('temperature', None)
    # UTF-8 byte count is a conservative input token ceiling for BPE models.
    input_ceiling = len((system + content).encode("utf-8")) + 512
    reservation = (input_ceiling * cfg.llm_input_rub_per_million + max_tokens * cfg.llm_output_rub_per_million) / 1_000_000
    # Reserve an attempt before sending; timeouts and process crashes never return this slot.
    day = reserve_budget(reservation, count_request=True)
    usage = None
    try:
        response = httpx.post(cfg.llm_base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {cfg.llm_api_key}"}, timeout=75,
            json=request_body)
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage")
        if body['choices'][0].get('finish_reason') == 'length':
            raise OutputTruncated('Ответ обрезан лимитом токенов')
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
        if isinstance(exc, OutputTruncated):
            error = ModelUnavailable('Ответ модели обрезан лимитом выходных токенов. Сократите требуемый ответ; автоматического повтора нет.')
        if isinstance(exc, httpx.HTTPStatusError):
            messages = {401: 'DeepSeek/API отклонил ключ (HTTP 401). Проверьте ключ в локальном .env.',
                402: 'На счёте провайдера недостаточно средств (HTTP 402). Повторный запрос не выполнялся.',
                429: 'Провайдер ограничил частоту запросов (HTTP 429). Автоматического повтора нет.'}
            error = ModelUnavailable(messages.get(exc.response.status_code,
                f'Провайдер LLM вернул HTTP {exc.response.status_code}. Автоматического повтора нет.'))
    finally:
        valid_usage = isinstance(usage, dict) and all(isinstance(usage.get(k), int) and usage[k] >= 0 for k in ("prompt_tokens", "completion_tokens"))
        actual = reservation
        if valid_usage:
            actual = (usage["prompt_tokens"] * cfg.llm_input_rub_per_million + usage["completion_tokens"] * cfg.llm_output_rub_per_million) / 1_000_000
        with SessionLocal() as db:
            # Keep the same row-lock order as reservation under concurrent workers.
            db.execute(update(LlmAllowance).where(LlmAllowance.key == ALLOWANCE_KEY)
                       .values(spent=LlmAllowance.spent + actual - reservation))
            db.execute(update(Budget).where(Budget.day == day).values(spent=Budget.spent + actual - reservation))
            db.add(Usage(run_id=run_id, model=model, input_tokens=usage["prompt_tokens"] if valid_usage else 0,
                         output_tokens=usage["completion_tokens"] if valid_usage else 0,
                         cost_rub=actual, status=status if valid_usage else status + "_reserved"))
            db.commit()
    if result is None:
        raise error
    return result
