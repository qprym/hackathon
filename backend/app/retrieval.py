import re
from datetime import timedelta
from sqlalchemy import func, select
from .db import utcnow
from .models import Document, Event
from .bank_relevance import SEARCH_VERSION, subject_match, subjects, words

RANKING_VERSION = 'context-subject-v2'

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
    features = context["features"]
    has = lambda k: features.get(k, {}).get("value") is True
    topics = set(event.topics)
    commodity = subjects(event.title) - {'policy_rate', 'deposit_rates', 'interest_rates'}
    industry_subjects = subjects(context['industry'])
    if re.search(r'металлоконструк|металлопрокат|черн\w* металл', context['industry'], re.I):
        industry_subjects.add('steel')
    subject_link = bool(commodity & industry_subjects)
    direct = False
    score, reasons, keys = 0.0, [], []
    def add(points, reason, key):
        nonlocal score
        score += points
        reasons.append(reason)
        keys.append(key)
    if "rates" in topics and has("CL_PRODUCT_LOA_MARK"):
        add(30, "Есть кредитные продукты: важны условия финансирования", "CL_PRODUCT_LOA_MARK")
        direct = not commodity
    if "rates" in topics and has("CL_PRODUCT_DEP_MARK"):
        add(16, "Есть депозиты: важна доходность размещения средств", "CL_PRODUCT_DEP_MARK")
        direct = direct or not commodity
    if "fx" in topics and has("FTS_FLAG"):
        add(6 if commodity else 18, "Есть сведения ФТС; товары, валюты и направления операций неизвестны", "FTS_FLAG")
    sector = classify(context["industry"])
    for topic in topics.intersection(sector):
        if commodity and not subject_link and topic != 'logistics':
            continue
        add(20, f"Связь с деятельностью: {TOPIC_NAMES[topic].lower()}", "MAINOKVED_NAME")
        direct = direct or not commodity or subject_link
    if commodity & {'diesel', 'gasoline', 'fuel'} and re.search(r'перевоз|автомобильн\w*\s+(?:грузов\w*\s+)?транспорт', context['industry'], re.I):
        add(2 if 'logistics' in topics else 22,
            "Топливо может влиять на затраты перевозчика; состав парка, договоры и доля затрат неизвестны", "MAINOKVED_NAME")
    if subject_link:
        add(16, "Предмет новости связан с указанным видом деятельности", "MAINOKVED_NAME")
        direct = True
    if "logistics" in topics and 'logistics' not in sector and any(t in context["industry"].lower() for t in ("производ", "торгов", "перевоз")):
        add(6, "Возможна косвенная связь через движение товаров; конкретные маршруты и грузы неизвестны", "MAINOKVED_NAME")
    concentration = features.get("outgoing_concentration", {}).get("value", 0)
    if topics.intersection({"logistics", "liquidity"}) and concentration > .5 and not commodity:
        add(10, "Исходящие платежи сконцентрированы на одном контрагенте", "outgoing_concentration")
    related = [c for c in context.get("counterparties", []) if topics.intersection(classify(c["industry"]))]
    if related and not commodity:
        add(6, "Тема затрагивает отрасли связанных платежами компаний", "counterparty_count")
    if context["region"].lower() not in ("не указан", "") and context["region"].lower() in event.title.lower():
        add(14, "Событие относится к региону регистрации", "REGION")
    exposure = 'direct' if direct else ('indirect' if keys else 'unknown')
    note = ('Есть связь с признаками профиля; величина финансового эффекта не установлена.' if direct else
            'Косвенная связь; конкретный товар, объём операций и механизм влияния нужно уточнить.' if commodity and keys else
            'Косвенная связь по профилю; применимость события нужно уточнить.' if keys else
            'Прямая связь с компанией по доступным признакам не установлена.')
    role_score = sum(ROLE_WEIGHTS[role].get(t, 0) for t in topics)
    score += min(role_score, 18)
    if role_score:
        reasons.append(f"Соответствует приоритетам роли {role}")
    age = max(((as_of or utcnow()) - event.published_at).total_seconds() / 86400, 0)
    score += max(0, 8 - age / 3)
    # RSS and full text of the same article are not independent corroboration.
    ceiling = 100 if direct else 39 if keys else 24
    return {"score": round(min(score, ceiling), 1), "reasons": reasons or [note],
            "feature_keys": list(dict.fromkeys(keys)), 'exposure': {'level': exposure, 'note': note},
            'ranking_version': RANKING_VERSION}


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
    candidates.extend(db.scalars(stmt.order_by(Document.published_at.desc()).limit(500)).all())
    unique = {d.id: d for d in candidates}
    scored = []
    for doc in unique.values():
        for index, chunk in enumerate(doc.chunks):
            if chunk.get('extraction') == 'ocr' and chunk.get('confidence', 0) < 65:
                continue
            if kind == 'bank':
                body = chunk['text']
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
            "date_kind": doc.ingestion_meta.get('date_kind','publication'), "date_source":doc.ingestion_meta.get('date_source')}


def event_evidence(db, event):
    result = []
    for doc_id in event.document_ids:
        doc = db.get(Document, doc_id)
        if doc:
            result.extend(evidence(doc, i, chunk) for i, chunk in enumerate(doc.chunks[:3]))
    return result[:8]
