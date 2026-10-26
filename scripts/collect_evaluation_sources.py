"""Collect public primary material for evaluation, with no model calls or paywall bypass."""
import argparse
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from defusedxml import ElementTree

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.ingestion import safe_fetch, extract_article, clean_text
from app.retrieval import classify


def collect(existing):
    now=datetime.now(timezone.utc)
    candidates={};errors=[]
    # RssNews includes updates of registries/statistical landing pages, not only
    # news. Use press releases so a page update cannot become a fabricated event.
    for key,url in [('cbr','https://www.cbr.ru/rss/RssPress')]:
        root=ElementTree.fromstring(safe_fetch(url))
        for item in root.findall('.//item'):
            candidates[item.findtext('link')]={'title':item.findtext('title'),'url':item.findtext('link'),
                'published_at':parsedate_to_datetime(item.findtext('pubDate')).astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
                'summary':clean_text(item.findtext('description') or ''),'key':key,'discovery_url':url}
    for section in ('business','economics','finance','health'):
        url='https://www.vedomosti.ru/'+section
        try:
            page=BeautifulSoup(safe_fetch(url),'html.parser')
            for a in page.select('a[href]'):
                link=urljoin(url,a['href']);title=a.get_text(' ',strip=True)
                if re.search(r'/(?:business|economics|finance|health)(?:/[a-z_]+)?/(?:articles|news)/\d{4}/\d{2}/\d{2}/',link) and 15<len(title)<300:
                    candidates.setdefault(link,{'title':title,'url':link,'key':'vedomosti','discovery_url':url})
        except Exception as e: errors.append({'url':url,'error':str(e)[:200]})
    known={s.get('url') for e in existing['events'] for s in e['sources']}
    def recent_url(url):
        stamp=re.search(r'/(\d{4})/(\d{2})/(\d{2})/',url)
        return not stamp or (now-datetime(*map(int,stamp.groups()),tzinfo=timezone.utc)).days<=61
    pending=[v for k,v in candidates.items() if k and k not in known and recent_url(k)]

    def fetch(item):
        raw=safe_fetch(item['url']);page=BeautifulSoup(raw,'html.parser')
        meta=lambda name:page.select_one(f'meta[property="{name}"],meta[name="{name}"]')
        title_node=meta('og:title')
        title=(title_node.get('content') if title_node else item['title']).removesuffix(' - Ведомости').strip()
        date=item.get('published_at')
        if not date:
            stamp=meta('article:published_time') or meta('datePublished')
            if stamp:date=datetime.fromisoformat(stamp['content'].replace('Z','+00:00')).astimezone(timezone.utc).replace(tzinfo=None).isoformat()
        if not date:
            # A URL supplies a publication day, never an invented time of day.
            m=re.search(r'/(\d{4})/(\d{2})/(\d{2})/',item['url'])
            if m:date='-'.join(m.groups())+'T00:00:00'
        if not date:raise ValueError('No publication date')
        when=datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
        if when>now or (now-when).days>60:raise ValueError('Outside predeclared 60-day window')
        try:content,info=extract_article(raw,item['key'])
        except ValueError as e:
            description=meta('description') or meta('og:description')
            content=item.get('summary') or (description.get('content','') if description else '')
            info={'coverage':'summary','method':'public:description','warning':str(e)}
        if len(content)<60:raise ValueError('Insufficient public text')
        key=hashlib.sha256(item['url'].encode()).hexdigest()
        source={'id':'public-'+key[:24],'title':title,'url':item['url'],'publisher':'Банк России' if item['key']=='cbr' else 'Ведомости',
                'published_at':date,'content':content,**info,'fetched_at':now.isoformat(),'discovery_url':item['discovery_url']}
        return {'id':'candidate-'+key[:24],'title':title,'published_at':date,'topics':classify(title+' '+content),
                'document_ids':[source['id']],'sources':[source]}
    fresh=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(fetch,item):item['url'] for item in pending}
        for job in as_completed(jobs):
            try:fresh.append(job.result())
            except Exception as e:errors.append({'url':jobs[job],'error':str(e)[:200]})
    return {**existing,'as_of':now.replace(tzinfo=None).isoformat(), 'events':existing['events']+sorted(fresh,key=lambda e:e['id']),
            'collection':{'new_public_events':len(fresh),'attempted':len(pending),'errors':errors,'model_calls':0}}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--corpus',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise SystemExit('Output exists')
    result=collect(json.loads(a.corpus.read_text(encoding='utf8')))
    with a.output.open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({**result['collection'],'errors':len(result['collection']['errors'])},ensure_ascii=False))
