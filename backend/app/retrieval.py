import re
from datetime import timedelta
from sqlalchemy import func, select
from .db import utcnow
from .models import Document, Event

TOPICS = {
    "rates": ("ставк", "кредит", "процент", "рефинанс", "денежно-кредит"),
    "fx": ("валют", "курс", "импорт", "экспорт", "трансгранич", "внешней торгов"),
    "logistics": ("логист", "перевоз", "поставк", "порт", "транспорт", "груз"),
    "commodities": ("сырь", "металл", "нефт", "золот", "сталь", "энергоресурс"),
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
    def matches(stem):
        # «ставка» must not match «поставка»; «порт» must not match «портфель».
        pattern = r"\bпорт(?:а|у|ом|е|ы|ов|ам|ах|ами)?\b" if stem == "порт" else r"\b" + re.escape(stem)
        return re.search(pattern, lower) is not None
    return [topic for topic, stems in TOPICS.items() if any(matches(s) for s in stems)]


def tokens(text):
    return {w[:7] for w in re.findall(r"[а-яёa-z]{4,}", text.lower())}


def rank_event(event, context, role):
    features = context["features"]
    has = lambda k: features.get(k, {}).get("value") is True
    topics = set(event.topics)
    score, reasons, keys = 0.0, [], []
    def add(points, reason, key):
        nonlocal score
        score += points
        reasons.append(reason)
        keys.append(key)
    if "rates" in topics and has("CL_PRODUCT_LOA_MARK"):
        add(30, "Есть кредитные продукты: важны условия финансирования", "CL_PRODUCT_LOA_MARK")
    if "rates" in topics and has("CL_PRODUCT_DEP_MARK"):
        add(16, "Есть депозиты: важна доходность размещения средств", "CL_PRODUCT_DEP_MARK")
    if "fx" in topics and has("FTS_FLAG"):
        add(28, "Есть сведения ФТС: требуется оценка внешнеторговой экспозиции", "FTS_FLAG")
    sector = classify(context["industry"])
    for topic in topics.intersection(sector):
        add(20, f"Связь с деятельностью: {TOPIC_NAMES[topic].lower()}", "MAINOKVED_NAME")
    if "logistics" in topics and any(t in context["industry"].lower() for t in ("производ", "торгов", "перевоз")):
        add(18, "Деятельность связана с движением товаров", "MAINOKVED_NAME")
    concentration = features.get("outgoing_concentration", {}).get("value", 0)
    if topics.intersection({"logistics", "liquidity"}) and concentration > .5:
        add(10, "Исходящие платежи сконцентрированы на одном контрагенте", "outgoing_concentration")
    related = [c for c in context.get("counterparties", []) if topics.intersection(classify(c["industry"]))]
    if related:
        add(6, "Тема затрагивает отрасли связанных платежами компаний", "counterparty_count")
    if context["region"].lower() not in ("не указан", "") and context["region"].lower() in event.title.lower():
        add(14, "Событие относится к региону регистрации", "REGION")
    role_score = sum(ROLE_WEIGHTS[role].get(t, 0) for t in topics)
    score += min(role_score, 18)
    if role_score:
        reasons.append(f"Соответствует приоритетам роли {role}")
    age = max((utcnow() - event.published_at).total_seconds() / 86400, 0)
    score += max(0, 8 - age / 3)
    score += min(len(event.document_ids), 3)
    return {"score": round(min(score, 100), 1), "reasons": reasons or ["Общий экономический контекст; прямая связь пока не установлена"],
            "feature_keys": list(dict.fromkeys(keys))}


def search_documents(db, query, kind=None, before=None, synthetic=False, limit=6):
    stmt = select(Document).where(Document.synthetic == synthetic)
    if kind:
        stmt = stmt.where(Document.kind == kind)
    if before:
        stmt = stmt.where(Document.published_at <= before)
    query_tokens = tokens(query)
    query_topics = set(classify(query))
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
            overlap = len(query_tokens & tokens(chunk["text"]))
            topic_match = len(query_topics & set(doc.topics))
            if query_topics and not topic_match and overlap < 3:
                continue
            if not query_topics and overlap < 2:
                continue
            score = overlap + topic_match * 3
            if score:
                scored.append((score, doc, index, chunk))
    scored.sort(key=lambda row: (row[0], row[1].published_at), reverse=True)
    return [evidence(doc, index, chunk) for _, doc, index, chunk in scored[:limit]]


def evidence(doc, index, chunk):
    return {"id": f"{doc.id}:{index}", "document_id": doc.id, "title": doc.title, "kind": doc.kind,
            "publisher": doc.publisher, "url": doc.url, "published_at": doc.published_at.isoformat() + "Z",
            "excerpt": chunk["text"], "page": chunk.get("page"), "synthetic": doc.synthetic,
            "coverage": doc.ingestion_meta.get("coverage", "provided")}


def event_evidence(db, event):
    result = []
    for doc_id in event.document_ids:
        doc = db.get(Document, doc_id)
        if doc:
            result.extend(evidence(doc, i, chunk) for i, chunk in enumerate(doc.chunks[:3]))
    return result[:8]
