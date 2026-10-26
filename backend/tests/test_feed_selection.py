from copy import deepcopy
from app.feed_selection import assemble_feed, edition_family


def entry(key,score,topics,*,level='indirect',date='2026-10-23T12:00:00Z',title=None,publisher='Источник'):
    return {'id':key,'title':title or key,'score':score,'topics':topics,'eligible':score>0,
            'event_group':key,'published_at':date,'publisher':publisher,'document_id':'doc-'+key,
            'exposure':{'level':level},'reasons':['Сохранённое обоснование модели'],'ranking_grounds':[{'quote':'Цитата'}]}


def test_background_repetition_changes_list_not_model_scores_or_evidence():
    rows=[entry('rate',48,['rates']),entry('repeat',40,['rates']),entry('sector',30,['labor','regulation'])]
    before=deepcopy(rows);out=assemble_feed(rows,role='CFO')
    assert [r['id'] for r in out]==['rate','sector','repeat']
    assert out[2]['score']==40 and out[2]['ordering']['list_priority']<30
    assert out[2]['reasons']==before[1]['reasons'] and out[2]['ranking_grounds']==before[1]['ranking_grounds']
    assert rows==before


def test_priority_and_role_are_respected_without_filling_industry_quota():
    rows=[entry('rate',48,['rates']),entry('repeat',40,['rates']),entry('low',8,['commodities']),entry('rejected',0,['labor'])]
    assert [r['id'] for r in assemble_feed(rows)][:3]==['rate','repeat','low']
    assert not assemble_feed(rows)[-1]['eligible']
    rows.append(entry('urgent',60,['rates'],level='direct'))
    assert assemble_feed(rows)[0]['id']=='urgent'
    rows=[entry('rate',48,['rates']),entry('repeat',40,['rates']),entry('sector',30,['labor'])]
    assert [r['id'] for r in assemble_feed(rows,role='TREASURER')]==['rate','repeat','sector']
    assert not any(r['ordering']['repeated_financial_topics'] for r in assemble_feed(rows,role='TREASURER'))


def test_new_financial_axis_and_industry_topics_are_not_treated_as_repeats():
    rows=[entry('rate',40,['rates']),entry('fx',39,['fx']),entry('drug',38,['demand']),entry('vaccine',37,['demand'])]
    out=assemble_feed(rows)
    assert [r['score'] for r in out]==[40,39,38,37]
    assert all(not r['ordering']['repeated_financial_topics'] for r in out)


def editions():
    return [entry('old',40,['rates'],title='Результаты мониторинга ставок организаций (01.10.2026)',date='2026-10-01T10:00:00Z'),
            entry('new',25,['rates'],title='Результаты мониторинга ставок организаций (21.10.2026)',date='2026-10-21T10:00:00Z')]


def test_recent_edition_keeps_original_score_and_links_to_history():
    rows=editions();out=assemble_feed(rows)
    assert len(out)==1 and out[0]['id']=='new' and out[0]['score']==25
    assert out[0]['previous_editions'][0]['id']=='old'
    assert out[0]['previous_editions'][0]['document_id']=='doc-old'
    assert len(assemble_feed(rows,compact_series=False))==2  # Explicit search includes history.


def test_unrelated_dates_publishers_priorities_and_unassessed_editions_are_not_folded():
    a,b=editions();b['publisher']='Другой источник';assert len(assemble_feed([a,b]))==2
    a,b=editions();b['published_at']='2026-10-22T10:00:00Z';assert edition_family(b) is None
    a,b=editions();a['exposure']['level']='direct';a['score']=80;assert len(assemble_feed([a,b]))==2
    a,b=editions();b.update(eligible=False,score=0);assert assemble_feed([a,b])[0]['id']=='old'


def test_duplicates_keep_links_and_order_is_independent_of_input_iteration():
    rows=[entry('a',40,['rates']),entry('b',40,['rates']),entry('c',30,['demand'])]
    rows[1]['event_group']='a'
    out=assemble_feed(rows)
    assert out==assemble_feed(list(reversed(rows)))
    assert len(out)==2 and out[0]['publication_event_count']==2
    assert len(out[0]['related_publications'])==1
