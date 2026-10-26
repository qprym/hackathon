from app.event_groups import group_records
from app.news_focus import source_focus


def record(key,title,url,content=''):
    return {'id':key,'title':title,'published_at':'2026-10-24T12:00:00','document_ids':[key],
            'sources':[{'url':url,'content':content}]}


def test_query_identifies_cbr_documents_but_tracking_does_not():
    rows=[record('a','Ставка','https://www.cbr.ru/press/PR/?file=rate.htm'),
          record('b','Рублёвые депозиты','https://www.cbr.ru/press/PR/?file=deposit.htm'),
          record('c','Обновлённое сообщение','https://www.cbr.ru/press/PR/?utm_source=x&file=rate.htm')]
    g=group_records(rows)
    assert g['a']==g['c'] and g['a']!=g['b']


def test_reworded_same_accident_grouped_but_other_industry_not_merged():
    rows=[record('a','Шесть человек погибли при столкновении микроавтобуса и поезда в ЕАО','https://example.com/a'),
          record('b','Погибшие в аварии с микроавтобусом и поездом в ЕАО были иностранцами','https://example.com/b'),
          record('c','Вырос экспорт золота','https://example.com/c'),
          record('d','Вырос экспорт дизеля','https://example.com/d')]
    g=group_records(rows)
    assert g['a']==g['b'] and g['c']!=g['d']


def test_focus_does_not_promote_background_or_short_rss_copy():
    focus=source_focus('Концерт', [{'content':'Краткий текст'}, {'content':'Отменён концерт в городе.\n\nРанее банк обсуждал ключевую ставку и кредитование.'}])
    assert 'Отменён концерт' in focus and 'ключевую ставку' not in focus
