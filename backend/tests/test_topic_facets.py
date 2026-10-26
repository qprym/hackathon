def test_topics_are_from_entire_collection_and_stay_stable_under_filters_and_pagination(client):
    params={'company_id':'demo-metal','role':'CFO','corpus':'synthetic','scope':'all','limit':1}
    first=client.get('/api/feed',params=params).json()
    facets=first['available_topics']
    assert len(facets)>len(first['items'][0]['topics'])
    unseen=next(t for t in facets if t not in first['items'][0]['topics'])
    filtered=client.get('/api/feed',params=params|{'topic':unseen}).json()
    assert filtered['available_topics']==facets and filtered['total']>0
    assert all(unseen in item['topics'] for item in filtered['items'])
    empty=client.get('/api/feed',params=params|{'q':'несуществующий поисковый запрос'}).json()
    assert empty['total']==0 and empty['available_topics']==facets
    next_page=client.get('/api/feed',params=params|{'feed_version':first['feed_version'],'offset':first['next_offset']}).json()
    assert next_page['available_topics']==facets
