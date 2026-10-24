import json
import pytest
from app import llm
from app.config import settings
from app.models import LlmAllowance


@pytest.mark.parametrize('room,expected', [(1.2,8000),(.8,6666),(.719,None)])
def test_review_preflight_keeps_input_ceiling_and_minimum(db,monkeypatch,room,expected):
    cfg=settings()
    for key,value in dict(llm_input_rub_per_million=30,llm_output_rub_per_million=120,
                          llm_test_limit_rub=30,llm_daily_limit_rub=20).items():
        monkeypatch.setattr(cfg,key,value)
    system='Все правила проверки'; payload={'evidence':['Полный текст']}
    input_cost=(len((system+json.dumps(payload,ensure_ascii=False)).encode('utf8'))+512)*30/1_000_000
    db.add(LlmAllowance(key=llm.ALLOWANCE_KEY,requests=63,spent=30-input_cost-room));db.commit()
    before=llm.allowance_status(db)
    if expected is None:
        with pytest.raises(llm.BudgetExceeded,match='минимум 6000'):
            llm.affordable_review_tokens(system,payload)
    else:
        assert abs(llm.affordable_review_tokens(system,payload)-expected)<=1
    db.expire_all()
    assert llm.allowance_status(db)==before
