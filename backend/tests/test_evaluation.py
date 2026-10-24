import importlib.util
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from app.models import Company, Document, Event


def script(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[2]/'scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bundle(db):
    now = datetime(2026,10,24)
    for c in ('a','b','c'):
        db.add(Company(id=c,name=c,industry='Перевозки',synthetic=False))
    for i in range(52):
        date = now-timedelta(hours=i)
        db.add(Document(id=f'd{i}',title=f'Новость {i}',kind='news',publisher='Редакция',published_at=date,
                        content='Полный текст новости',content_hash=str(i),synthetic=False))
        db.add(Event(id=f'e{i}',title=f'Новость {i}',document_ids=[f'd{i}'],topics=['logistics'],published_at=date,synthetic=False))
    db.commit()
    return script('export_evaluation').build_bundle(db,['a','b','c'],{'e0','e1'},as_of=now)[0]


def test_export_is_blind_complete_and_excludes_previous_events(bundle):
    assert len(bundle['events']) == 50
    assert sum(e['split']=='holdout' for e in bundle['events']) == 20
    assert not {'e0','e1'} & {e['id'] for e in bundle['events']}
    assert all(len(e['relevance']) == 9 and set(e['relevance'].values()) == {None} for e in bundle['events'])
    assert bundle['events'][0]['sources'][0]['content'] == 'Полный текст новости'
    assert len(bundle['contexts']) == 3
    assert all('score' not in e for e in bundle['events'])


def test_evaluator_requires_complete_labels_and_metadata(bundle):
    evaluate = script('evaluate').evaluate
    assert evaluate(bundle,'holdout')['status'] == 'incomplete'
    bundle['reviewer']='Human test fixture';bundle['reviewed_at']='2026-10-24'
    for e in bundle['events']:
        e['relevance'] = dict.fromkeys(e['relevance'],1)
    result = evaluate(bundle,'holdout')
    assert result['macro_average'] == 1
    assert len(result['precision_at_5']) == 9
    assert evaluate(deepcopy(bundle),'holdout') == result
    del bundle['events'][0]['relevance']['a:CEO']
    assert evaluate(bundle,'holdout')['status'] == 'incomplete'


def test_reviewer_metadata_does_not_make_empty_holdout_valid(bundle):
    bundle['events'] = []
    bundle['reviewer']='Human';bundle['reviewed_at']='2026-10-24'
    assert script('evaluate').evaluate(bundle,'holdout')['status'] == 'incomplete'


def test_historical_claims_cannot_pass_current_acceptance():
    data = {'reviewer':'Human','reviewed_at':'2026-10-24','claims':[
        {'assumption':False,'supported':True,'reviewer':'Human','outdated':True}]}
    result = script('evaluate_claims').evaluate_claims(data)
    assert result['status'] == 'historical_only'
    assert result['target_met'] is None
    data['claims'][0]['outdated'] = False
    assert script('evaluate_claims').evaluate_claims(data)['target_met'] is True
