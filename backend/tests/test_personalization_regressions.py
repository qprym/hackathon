from datetime import datetime
from types import SimpleNamespace
from app.event_groups import group_records
from app.retrieval import rank_event

NOW=datetime(2026,10,25)

def test_pharma_future_supply_and_trial_do_not_create_current_treasury_need():
    ctx={'industry':'Торговля оптовая фармацевтической продукцией','features':{}}
    for title in ['Фармацевтический завод начнёт выпуск лекарств в 2027 году',
                  'Фармпроизводитель подтвердил сертификат GMP EU',
                  'Опубликовано клиническое исследование препарата']:
        event=SimpleNamespace(title=title,published_at=NOW)
        assert rank_event(event,ctx,'CEO',as_of=NOW)['eligible']
        assert not rank_event(event,ctx,'TREASURER',as_of=NOW)['eligible']

def test_explicit_dated_deal_groups_followups_and_preserves_other_dates():
    def record(key,title,day):
        return {'id':key,'title':title,'published_at':NOW.isoformat(),
                'sources':[{'content':f'{day} октября президенты России и США договорились о поставках дизеля.'}]}
    records=[record('a','Министр прокомментировал внутренний рынок',9),
             record('b','Поставки топлива продолжаются',9),
             record('c','Подписано новое соглашение о поставках',24)]
    groups=group_records(records)
    assert groups['a']==groups['b'] and groups['b']!=groups['c']

def test_feed_hides_unrelated_stories_but_explicit_search_keeps_them(client):
    story={'title':'На концерте в Москве вручили награды',
           'content':'На концерте в Москве вручили награды музыкантам. В справочном разделе упомянута ключевая ставка.',
           'publisher':'Проверка','published_at':NOW.isoformat(),'synthetic':True}
    assert client.post('/api/admin/news',json=story).status_code==200
    feed=client.get('/api/feed?corpus=synthetic&company_id=demo-metal').json()['items']
    assert all(e['title']!=story['title'] for e in feed)
    search=client.get('/api/feed',params={'corpus':'synthetic','company_id':'demo-metal','q':'На концерте'}).json()['items']
    assert len(search)==1 and search[0]['exposure']['level']=='unknown'
