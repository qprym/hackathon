from datetime import datetime
from types import SimpleNamespace
import pytest
from app import agent
from app.llm import ModelUnavailable


def test_bank_selector_has_its_own_contract_and_lossless_short_ids(monkeypatch):
    event=SimpleNamespace(title='Событие',published_at=datetime(2026,10,25))
    candidates=[{'id':'a-long-source-id:123','excerpt':'Позиция банка','document_id':'original-document'}]
    sources=[{'excerpt':'Полная статья. '*5000}]
    context={'features':{'product':{'value':True}},'missing':['Условия договора неизвестны']}
    def answer(policy,payload,**kwargs):
        assert 'bank_view' not in policy and 'impact' not in policy
        assert payload['event_sources']==sources and payload['context']==context
        assert payload['candidates'][0]['id']=='B1'
        assert payload['output_schema']['properties']['ordered_ids']['items']['enum']==['B1']
        return {'ordered_ids':['B1']}
    monkeypatch.setattr(agent,'complete_json',answer)
    assert agent.select_bank_evidence(event,context,'CFO',candidates,sources,'run')==candidates


@pytest.mark.parametrize('raw',[{'ordered_ids':['unknown']},{'bank_view':[]},{'ordered_ids':[],'impact':[]}])
def test_bank_selector_rejects_an_analysis_instead_of_source_ids(monkeypatch,raw):
    monkeypatch.setattr(agent,'complete_json',lambda *a,**kw:raw)
    with pytest.raises(ModelUnavailable):
        agent.select_bank_evidence(SimpleNamespace(title='Событие',published_at=datetime(2026,10,25)),{},'CFO',[{'id':'source'}],[],'run')
