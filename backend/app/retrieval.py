import re
from datetime import timedelta
from sqlalchemy import func, select
from .db import utcnow
from .models import Document, Event
from .bank_relevance import SEARCH_VERSION, subject_match, subjects, words

from .personalization import RANKING_VERSION, rank

NEWS_CONTEXT_VERSION = 'complete-articles-v2'
NEWS_FRAGMENT_CHARS = 1500

TOPICS = {
    "rates": ("ставк", "кредит", "процент", "рефинанс", "денежно-кредит"),
    "fx": ("валют", "курс", "импорт", "экспорт", "трансгранич", "внешней торгов"),
    "logistics": ("логист", "перевоз", "поставк", "порт", "транспорт", "груз"),
    "commodities": ("сырь", "металл", "нефт", "золот", "сталь", "энергоресурс", "дизел", "бензин", "топлив"),
    "demand": ("спрос", "потреблен", "рознич", "продаж", "торговл"),
    "regulation": ("регулир", "закон", "налог", "тариф", "пошлин", "отчетност"),
    "labor": ("труд", "зарплат", "кадр", "персонал", "работник"),
    "liquidity": ("ликвид", "платеж", "платёж", "оборотн", "депозит", "расчет", "расчёт"),
}
TOPIC_NAMES = {"rates": "Ставки и кредит", "fx": "Внешняя торговля", "logistics": "Логистика",
               "commodities": "Сырьевые рынки", "demand": "Спрос", "regulation": "Регулирование",
               "labor": "Рынок труда", "liquidity": "Ликвидность"}
ROLE_WEIGHTS = {
    "CEO": {"demand": 9, "commodities": 8, "regulation": 8, "labor": 7, "logistics": 6},
    "CFO": {"rates": 10, "liquidity": 8, "fx": 7, "regulation": 6},
    "TREASURER": {"liquidity": 12, "fx": 10, "rates": 8, "logistics": 3},
}


def classify(text):
    lower = text.casefold()
    lower = re.sub(r'кредитн\w*\s+рейтинг\w*', 'рейтинг', lower)
    def matches(stem):
        # «ставка» must not match «поставка»; «порт» must not match «портфель».
        pattern = r"\bпорт(?:а|у|ом|е|ы|ов|ам|ах|ами)?\b" if stem == "порт" else r"\b" + re.escape(stem)
        return re.search(pattern, lower) is not None
    return [topic for topic, stems in TOPICS.items() if any(matches(s) for s in stems)]


def tokens(text):
    return {w[:7] for w in re.findall(r"[а-яёa-z]{4,}", text.lower())}


def rank_event(event, context, role, *, as_of=None):
    return rank(event, context, role, as_of=as_of)


def search_documents(db, query, kind=None, before=None, synthetic=False, limit=6, focus=None):
    stmt = select(Document).where(Document.synthetic == synthetic)
    if kind:
        stmt = stmt.where(Document.kind == kind)
    if before:
        stmt = stmt.where(Document.published_at <= before)
    query_tokens = tokens(query)
    query_topics = set(classify(query))
    focus = focus or query
    # PostgreSQL supplies indexed linguistic search; lexical/topic matching broadens recall.
    candidates = []
    if db.bind.dialect.name == "postgresql" and query.strip():
        vector = func.to_tsvector('russian', Document.title + ' ' + Document.content)
        tsquery = func.websearch_to_tsquery('russian', query)
        candidates.extend(db.scalars(stmt.where(vector.op('@@')(tsquery)).order_by(
            func.ts_rank_cd(vector, tsquery).desc()).limit(30)).all())
    # Bank library must remain searchable beyond the newest 500 pages/documents.
    candidates.extend(db.scalars(stmt.order_by(Document.published_at.desc()) if kind=='bank'
        else stmt.order_by(Document.published_at.desc()).limit(500)).all())
    unique = {d.id: d for d in candidates}
    scored = []
    for doc in unique.values():
        for index, chunk in enumerate(doc.chunks):
            if chunk.get('extraction') == 'ocr' and chunk.get('confidence', 0) < 65:
                continue
            if kind == 'bank':
                body = chunk['text']
                if chunk.get('content_type') in ('table','chart') and not chunk.get('numeric_verified'):
                    continue
                if chunk.get('extraction') == 'ocr' and (not re.match(r'^[А-ЯЁA-Z]', body) or not re.search(r'[.!?:;]$', body)):
                    continue
                if len(re.findall(r'[а-яёa-z]{3,}', body.lower())) < 15:
                    continue
                if re.search(r'финансовые результаты.{0,100}(?:МСФО|отчетност)|данный материал распространяется|не является индивидуальной инвестиционной', body, re.I|re.S):
                    continue
                if sum(c.isdigit() for c in body) / max(len(body), 1) > .16:
                    continue
            relevance = None
            if kind == 'bank':
                relevance = subject_match(focus, chunk['text'])
                if relevance and relevance['level'] == 'irrelevant':
                    continue
                if relevance is None:
                    # Broad themes and speech boilerplate cannot admit a document.
                    anchors = words(focus) & words(chunk['text'])
                    title_anchors = words(focus) & words(doc.title)
                    if len(anchors) < 2 and not (anchors and title_anchors):
                        continue
                    relevance = {'level': 'direct', 'matched_terms': sorted(anchors),
                                 'reason': 'Совпадают предметные слова; это поисковая связь, не доказательство вывода.'}
            overlap = len(query_tokens & tokens(chunk["text"]))
            topic_match = len(query_topics & set(classify(chunk['text'])))
            if not overlap and not relevance:
                continue
            if not relevance and query_topics and not topic_match and overlap < 3:
                continue
            if not relevance and not query_topics and overlap < 2:
                continue
            title_match = len(query_tokens & tokens(doc.title))
            score = overlap + topic_match * 3 + title_match * 2
            score += len(query_topics & set(classify(doc.title))) * 2
            if relevance:
                score += 100 if relevance['level'] == 'direct' else 20
            if before:
                score -= min(max((before - doc.published_at).days - 90, 0) / 365, 5)
            if score:
                scored.append((score, doc, index, chunk, relevance))
    scored.sort(key=lambda row: (bool(row[4] and row[4]['level'] == 'direct'), row[0], row[1].published_at), reverse=True)
    result, counts = [], {}
    for _, doc, index, chunk, relevance in scored:
        if kind == 'bank' and counts.get(doc.id, 0) >= 2:
            continue
        item = evidence(doc, index, chunk)
        if relevance:
            item['relevance'] = {**relevance, 'focus': focus, 'version': SEARCH_VERSION}
        result.append(item)
        counts[doc.id] = counts.get(doc.id, 0) + 1
        if len(result) >= limit:
            break
    return result


def evidence(doc, index, chunk):
    return {"id": f"{doc.id}:{index}", "document_id": doc.id, "title": doc.title, "kind": doc.kind,
            "publisher": doc.publisher, "url": doc.url, "published_at": doc.published_at.isoformat() + "Z",
            "excerpt": chunk["text"], "page": chunk.get("page"), "synthetic": doc.synthetic,
            "coverage": doc.ingestion_meta.get("coverage", "provided"),
            "extraction": chunk.get('extraction', 'text'), "confidence": chunk.get('confidence'),
            "date_kind": doc.ingestion_meta.get('date_kind','publication'), "date_source":doc.ingestion_meta.get('date_source'),
            'visual_status':chunk.get('visual_status','not_verified') if doc.kind=='bank' else None,
            'numeric_tables_status':chunk.get('numeric_tables_status','not_verified') if doc.kind=='bank' else None,
            'content_type':chunk.get('content_type','text'),'numeric_verified':chunk.get('numeric_verified',False)}


def bank_query_variants(query):
    """Broaden recall; these words never decide final applicability."""
    variants=[query]
    for pattern,expansion in (
        (r'дизел|топлив','дизельное топливо нефтепереработка нефтепродукты'),
        (r'металл|\bстал[ьи]\b|конструкц','металлопрокат сталь строительство'),
        (r'фарм|лекарств','фармацевтика лекарства дистрибуция'),
        (r'ставк|финансирован','денежно-кредитная политика стоимость фондирования')):
        if re.search(pattern,query,re.I):variants.append(expansion)
    return variants


def bank_sections(db,queries,event,limit=12):
    found={};scores={}
    variants=dict.fromkeys(v for q in queries for v in bank_query_variants(q))
    for variant in variants:
        for rank,item in enumerate(search_documents(db,variant,kind='bank',before=event.published_at,
                synthetic=event.synthetic,limit=limit,focus=event.title),1):
            found.setdefault(item['id'],item)
            scores[item['id']]=scores.get(item['id'],0)+1/(60+rank)
    ordered=sorted(found.values(),key=lambda e:(e.get('relevance',{}).get('level')!='direct',-scores[e['id']],e['id']))
    return ordered[:limit]


def expand_bank_pages(db,evidence_items):
    """Give the selector paragraph context from the same original page, with exact provenance."""
    expanded=[]
    for item in evidence_items:
        doc=db.get(Document,item['document_id']);page=item.get('page')
        original=next((p.get('text') for p in doc.ingestion_meta.get('pages',[]) if p.get('number')==page),None) if doc and page else None
        if not original and doc and page:
            chunks=[c for c in doc.chunks if c.get('page')==page and (c.get('extraction')!='ocr' or c.get('confidence',0)>=65)]
            original='\n\n'.join(c['text'] for c in sorted(chunks,key=lambda c:c.get('offset',0)))
        # Keep the selected cited excerpt unchanged; extra context cannot become an unanchored citation.
        expanded.append({**item,'page_context':original or item['excerpt']})
    return expanded


def event_evidence(db, event, document_ids=None):
    # Splitting provides exact citations; it never limits the input article.
    # A provider/context/budget error must stop the run, never shorten its text.
    docs=[doc for key in (document_ids or event.document_ids) if (doc:=db.get(Document,key)) and doc.synthetic==event.synthetic]
    docs.sort(key=lambda d:(d.ingestion_meta.get('coverage')!='summary',len(d.content)),reverse=True)
    result=[];included=[]
    for doc in docs:
        if any(doc.publisher==old.publisher and doc.content in old.content for old in included):
            continue  # The shorter RSS copy adds no context to the full article.
        length=len(doc.content)
        for start in range(0,length,NEWS_FRAGMENT_CHARS):
            chunk={'text':doc.content[start:min(start+NEWS_FRAGMENT_CHARS,length)],'page':None}
            item=evidence(doc,f'text-{start}',chunk)
            item['context_span']={'start':start,'end':min(start+NEWS_FRAGMENT_CHARS,length),
                'document_characters':len(doc.content),'included_characters':length,'truncated':length<len(doc.content)}
            result.append(item)
        included.append(doc)
    if result:
        result[0]['event_context']={'version':NEWS_CONTEXT_VERSION,'omitted_document_ids':[],
                                  'full_stored_text':True}
    return result
