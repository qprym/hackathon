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


def test_complete_feed_metrics_count_missing_slots_recall_and_review_rejections():
    metric=script('evaluate_full_feed').metrics
    records=[{'id':str(i),'event_group':str(i),'relevance':{'company:CFO':1 if i<3 else 0}} for i in range(6)]
    result=metric(records,['0','1','1','5'],'company:CFO',draft_positive=['0','1','2','5'])
    assert result['precision_at_5']==.4 and result['precision_at_5_ceiling']==.6
    assert result['recall']==pytest.approx(2/3)
    assert result['duplicate_cards']==1 and result['review_false_rejections_on_ai_labels']==1


@pytest.fixture
def bundle(db):
    now = datetime(2026,10,24)
    for c in ('a','b','c'):
        db.add(Company(id=c,name=c,industry='Перевозки',synthetic=False))
    titles=['Изменились ключевые ставки','Промышленность увеличила выпуск металлов',
            'Изменились таможенные пошлины','Изменились сроки грузовых перевозок','Открылась культурная выставка','Фармацевтический рынок изменился']
    for i in range(90):
        date = now-timedelta(hours=i)
        db.add(Document(id=f'd{i}',title=f'Новость {i}',kind='news',publisher='Редакция',published_at=date,
                        content='Полный текст новости',content_hash=str(i),synthetic=False))
        db.add(Event(id=f'e{i}',title=f'{titles[i%6]} — проверка {i}',document_ids=[f'd{i}'],topics=['logistics'],published_at=date,synthetic=False))
    db.commit()
    return script('export_evaluation').build_bundle(db,['a','b','c'],{'e0','e1'},as_of=now)[0]


def test_export_is_blind_complete_and_excludes_previous_events(bundle):
    assert len(bundle['events']) == 50
    assert sum(e['split']=='holdout' for e in bundle['events']) == 20
    assert not {'e0','e1'} & {e['id'] for e in bundle['events'] if e['split']=='holdout'}
    assert all(len(e['relevance']) == 9 and set(e['relevance'].values()) == {None} for e in bundle['events'])
    assert bundle['events'][0]['sources'][0]['content'] == 'Полный текст новости'
    assert len(bundle['contexts']) == 3
    assert all('score' not in e for e in bundle['events'])
    assert len({e['event_group'] for e in bundle['events']})==50
    assert len({e['stratum'] for e in bundle['events']})==6


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


def test_ai_labels_and_cross_split_clusters_cannot_pass_acceptance(bundle):
    bundle.update(reviewer='AI review', reviewer_kind='ai', independent=False, reviewed_at='2026-10-25')
    for e in bundle['events']:
        e['relevance'] = dict.fromkeys(e['relevance'], 1)
    bundle['events'][0]['event_group'] = bundle['events'][20]['event_group'] = 'same-incident'
    result = script('evaluate').evaluate(bundle, 'holdout')
    assert result['status'] == 'ai_reviewed'
    assert result['macro_average'] == 1
    assert result['target_met'] is None and not result['acceptance_eligible']
    assert result['cross_split_event_groups'] == ['same-incident']
    bundle.update(reviewer_kind='human', independent=True)
    assert script('evaluate').evaluate(bundle, 'holdout')['target_met'] is None
    del bundle['events'][20]['event_group']
    for e in bundle['events']:
        e['relevance']['a:CEO'] = 0
    result = script('evaluate').evaluate(bundle, 'holdout')
    assert result['target_met'] is False
    assert result['precision_at_5_ceiling']['a:CEO'] == 0


def test_ai_claim_labels_cannot_pass_independent_acceptance():
    data = {'reviewer':'AI', 'reviewer_kind':'ai', 'independent':False, 'reviewed_at':'2026-10-25',
            'claims':[{'assumption':False,'supported':True,'reviewer':'AI','outdated':False}]}
    result = script('evaluate_claims').evaluate_claims(data)
    assert result['current']['supported_fraction'] == 1
    assert result['target_met'] is None and not result['acceptance_eligible']


def test_saved_neural_evaluation_requires_matching_context_and_checked_predictions(bundle):
    from app.semantic_ranking import fingerprint
    bundle.update(reviewer='AI',reviewer_kind='ai',independent=False,reviewed_at='2026-10-25')
    for event in bundle['events']:event['relevance']=dict.fromkeys(event['relevance'],1)
    predictions={'selection_version':'test','review_version':'review-test','model_id':'test-model',
        'context_fingerprints':{c:fingerprint(bundle['contexts'][c]) for c in bundle['companies']},
        'predictions':{c:{e['id']:{'status':'completed','result':{'review':{'version':'review-test'},
            'roles':{r:{'score':30,'relevance':1} for r in ('CEO','CFO','TREASURER')}}} for e in bundle['events']} for c in bundle['companies']}}
    evaluate=script('evaluate').evaluate_predictions
    result=evaluate(bundle,predictions,'holdout')
    assert result['macro_average']==1 and result['target_met'] is None
    company=bundle['companies'][0];key=next(e['id'] for e in bundle['events'] if e['split']=='holdout')
    predictions['predictions'][company][key]['status']='failed'
    assert evaluate(bundle,predictions,'holdout')['status']=='incomplete'
    predictions['context_fingerprints'][company]='different'
    assert 'context differs' in evaluate(bundle,predictions,'holdout')['message']


def test_short_feed_does_not_turn_precision_at_five_into_precision_at_two(bundle):
    bundle.update(reviewer='AI',reviewer_kind='ai',reviewed_at='2026-10-25')
    for e in bundle['events']:e['relevance']=dict.fromkeys(e['relevance'],1)
    titles={e['title'] for e in bundle['events'][:2]}
    result=script('evaluate').evaluate(bundle,'holdout',ranker=lambda event,*args,**kwargs:{'score':1,'eligible':event.title in titles})
    assert set(result['precision_at_5'].values())=={.4}
    assert set(result['returned_at_5'].values())=={2}
    assert set(result['precision_of_returned'].values())=={1.0}


def test_sampler_rejects_unbalanced_corpus_instead_of_filling_latest_news(bundle):
    for e in bundle['events']:e['title']='Культурная выставка номер '+e['id']
    with pytest.raises(ValueError,match='collect sources'):
        script('sample_evaluation').sample({'events':bundle['events'],'as_of':bundle['ranking_as_of']},bundle)
