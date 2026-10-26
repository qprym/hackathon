"""Conservative publication groups shared by sampling and feed diversity.

Groups retain original documents and disagreements; they are not fact merging.
"""
import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from urllib.parse import urlsplit, parse_qsl, urlencode

GROUPING_VERSION = 'publication-groups-v2'
STOP = set('росси россий россии украи сообщ заяви назва после перед котор также этого может новых новый новый своем свое стали станет будет будут года году россие'.split())


def terms(text):
    words={w[:5] for w in re.findall(r'[а-яёa-z]{4,}', text.casefold().replace('ё','е')) if w[:5] not in STOP}
    words.update(w.lower() for w in re.findall(r'\b[А-ЯЁ]{2,6}\b',text) if w not in {'РФ','США','МВД','ЦБ','ООО','ПАО','АО'})
    return words


def referenced_trade_agreements(record):
    """Follow explicit dated interstate deals across follow-up publications.

    A common fuel/country alone is insufficient: the source must name a dated
    agreement involving government leaders. Documents and conflicting claims stay intact.
    """
    identities=[]
    countries={'RU':r'росси', 'US':r'\bсша\b|американ', 'CN':r'китай|китаем',
               'IN':r'инди[яиейю]|индийск', 'FR':r'франц', 'EU':r'евросоюз|\bес\b'}
    goods={'diesel':r'дизел|дизтоплив','gas':r'\bгаз[ауе]?\b','gold':r'золот','steel':r'\bсталь\b|рынок стали'}
    for source in record.get('sources',[]):
        for paragraph in re.split(r'\n\s*\n',source.get('content','')):
            if not re.search(r'договорил|соглашен|сделк',paragraph,re.I) or not re.search(r'президент|премьер|министр',paragraph,re.I):continue
            date=re.search(r'\b(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)(?:\s+(20\d{2}))?',paragraph,re.I)
            route=tuple(k for k,v in countries.items() if re.search(v,paragraph,re.I))
            subjects=tuple(k for k,v in goods.items() if re.search(v,paragraph,re.I))
            if date and len(route)>=2 and subjects:
                stamp=(date[3] or record['published_at'][:4],date[2].lower(),date[1])
                identities.append(('trade-agreement',stamp,route,subjects))
    return identities


def group_records(records):
    records = sorted(records, key=lambda r:r['id'])
    parent = list(range(len(records)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def join(i,j):
        a,b = root(i),root(j)
        parent[max(a,b)] = min(a,b)
    heads = [terms(r['title']) for r in records]
    bodies = [terms(' '.join(s.get('content','')[:5000] for s in r.get('sources',[]))) for r in records]
    freq = Counter(t for head in heads for t in head)
    weight = {t:math.log(1+len(records)/(1+n)) for t,n in freq.items()}
    dates = [datetime.fromisoformat(r['published_at'].replace('Z','+00:00')).replace(tzinfo=None) for r in records]
    seen, inverted = {}, defaultdict(list)
    for i,r in enumerate(records):
        identities = [('title',' '.join(r['title'].casefold().split()))]
        identities += [('doc',d) for d in r.get('document_ids',[])]
        identities += referenced_trade_agreements(r)
        for s in r.get('sources',[]):
            if s.get('url'):
                u=urlsplit(s['url'])
                query=urlencode(sorted((k,v) for k,v in parse_qsl(u.query) if not k.startswith('utm_') and k not in ('fbclid','gclid')))
                identities.append(('url',u.netloc.casefold()+u.path.rstrip('/')+'?'+query))
        for identity in identities:
            if identity in seen: join(i,seen[identity])
            else: seen[identity]=i
        candidates = set(j for t in heads[i] for j in inverted[t])
        for j in candidates:
            objects = lambda title: {key for key,pattern in {
                'gold':r'золот', 'diesel':r'дизел|дизтоплив', 'gasoline':r'бензин',
                'gas':r'\bгаз[ауе]?\b', 'steel':r'\bстал[ьи]\b|металлопрокат',
            }.items() if re.search(pattern,title,re.I)}
            left_objects,right_objects=objects(r['title']),objects(records[j]['title'])
            if left_objects and right_objects and left_objects.isdisjoint(right_objects):
                continue
            if abs((dates[i]-dates[j]).total_seconds()) > 7*86400:
                continue
            shared=heads[i]&heads[j]
            union=heads[i]|heads[j]
            similarity=sum(weight[t] for t in shared)/max(sum(weight[t] for t in union),1)
            rare = [t for t in shared if freq[t] <= max(3,len(records)*.06)]
            body_overlap=len(bodies[i]&bodies[j])/max(min(len(bodies[i]),len(bodies[j])),1)
            # A shared place, publisher, broad topic or a lone company name is
            # insufficient. Exact URLs above still join conflicting revisions.
            shared_place = set(re.findall(r'\b[А-ЯЁ]{2,6}\b',r['title'])) & set(re.findall(r'\b[А-ЯЁ]{2,6}\b',records[j]['title'])) - {'РФ','США','МВД','ЦБ','ООО','ПАО','АО'}
            if ((shared_place and len(rare)>=3 and similarity>=.2) or
                (len(rare)>=2 and similarity>=.42) or
                (len(rare)>=1 and len(shared)>=2 and similarity>=.24 and body_overlap>=.72)):
                join(i,j)
        for t in heads[i]: inverted[t].append(i)
    members = defaultdict(list)
    for i,r in enumerate(records): members[root(i)].append(r['id'])
    return {key:'group-'+hashlib.sha256('|'.join(ids).encode()).hexdigest()[:16]
            for ids in members.values() for key in ids}


def diversified(entries):
    """Choose the highest-ranked representative; disclose all grouped event IDs."""
    grouped = defaultdict(list)
    for entry in entries: grouped[entry['event_group']].append(entry)
    result=[]
    for members in grouped.values():
        best=dict(members[0])
        best['related_event_ids']=[e['id'] for e in members[1:]]
        best['related_publications']=[{'document_id':e.get('document_id'),'title':e['title'],'publisher':e.get('publisher','')}
                                      for e in members[1:] if e.get('document_id')]
        best['publication_event_count']=len(members)
        result.append(best)
    return result
