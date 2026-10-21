from sqlalchemy import or_, select
from .models import Company, Link

PRODUCTS = {
    "CL_PRODUCT_LOA_MARK": "Кредитные продукты", "CL_PRODUCT_DEP_MARK": "Депозиты",
    "CL_PRODUCT_GAR_MARK": "Банковские гарантии", "CL_PRODUCT_LEA_MARK": "Лизинг",
    "FACTORING_MARK": "Факторинг", "CL_PRODUCT_RKO_MARK": "РКО", "CL_PRODUCT_ZPP_MARK": "Зарплатный проект",
}
FEATURE_LABELS = {**PRODUCTS, "SYNTHETIC_U": "Обезличенный ID", "ORG_TYPE": "Организационный тип",
    "OKFS_NAME": "Форма собственности", "COMPANY_AGE_YEARS_GRADATION": "Возраст компании",
    "ECO_MARK_LABEL": "Стадия жизненного цикла", "MAINOKVED_CODE": "ОКВЭД", "MAINOKVED_NAME": "Деятельность",
    "NEGATIVEMARK": "Наличие ключевого собственника (описание кейса)",
    "AMOUNT_WORKERS_FNS_GRADATION": "Численность по ФНС", "AMOUNT_WORKERS_SPARK_GRADATION": "Численность по СПАРК",
    "CL_TYPE": "Клиентский статус", "FTS_FLAG": "Сведения ФТС", "FTS_COUNTRY_NAME": "Страны по ФТС",
    "REVENUE_COMPANY": "Выручка", "GROUP_ID": "Группа", "CITY": "Город регистрации", "REGION": "Регион регистрации"}


def feature(value, source, status="fact", label=None):
    return {"value": value, "source": source, "status": status, "label": label or source}


def value(company, key, default=None):
    return company.features.get(key, {}).get("value", default)


def company_context(db, company, allowed_company_ids=None):
    allowed = set(allowed_company_ids) if allowed_company_ids is not None else None
    features = dict(company.features)
    features = {key: {**item, 'label': FEATURE_LABELS.get(key, item.get('label', key))} for key, item in features.items()}
    payments = db.scalars(select(Link).where(
        Link.kind == "payment", or_(Link.source_id == company.id, Link.target_id == company.id)
    )).all()
    self_payments = [p for p in payments if p.source_id == p.target_id]
    payments = [p for p in payments if p.source_id != p.target_id]
    outgoing = [p for p in payments if p.source_id == company.id]
    incoming = [p for p in payments if p.target_id == company.id]
    total = sum(p.amount or 0 for p in outgoing)
    if total:
        concentration = round(max(p.amount or 0 for p in outgoing) / total, 4)
        features["outgoing_concentration"] = feature(concentration,
            "Сумма PAY_AMT по исходящим связям предоставленной выборки", "calculated", "Концентрация исходящих платежей")
    features["counterparty_count"] = feature(len({p.target_id if p.source_id == company.id else p.source_id for p in payments}),
        "Платежные связи в предоставленной выборке", "calculated", "Контрагенты в выборке")
    related = []
    aliases = {}
    for p in sorted(payments, key=lambda p: p.amount or 0, reverse=True)[:10]:
        other_id = p.target_id if p.source_id == company.id else p.source_id
        permitted = allowed is None or other_id in allowed
        other = db.get(Company, other_id) if permitted else None
        if other and other.synthetic != company.synthetic:
            other = None
        alias = aliases.setdefault(other_id, f"Контрагент {len(aliases) + 1}")
        related.append({"id": other_id if permitted else alias,
                        "industry": other.industry if other else "Неизвестна",
                        "region": other.region if other else "Неизвестен",
                        "profile_available": other is not None,
                        "direction": "outgoing" if p.source_id == company.id else "incoming",
                        "amount": p.amount, "count": p.count})
    group = []
    if company.group_id:
        stmt = select(Company).where(Company.group_id == company.group_id, Company.synthetic == company.synthetic)
        if allowed is not None:
            stmt = stmt.where(Company.id.in_(allowed))
        group = [{"id": c.id, "industry": c.industry, "region": c.region} for c in db.scalars(
            stmt).all()]
    persons = db.scalars(select(Link).where(Link.kind == "person", Link.target_id == company.id)).all()
    shared_person_links = []
    if persons:
        stmt = select(Link).where(Link.kind == "person",
            Link.source_id.in_([p.source_id for p in persons]), Link.target_id != company.id)
        if allowed is not None:
            stmt = stmt.where(Link.target_id.in_(allowed))
        shared_person_links = [{"company_id": company_id, "relation": "Общее обезличенное физическое лицо; тип связи неизвестен"}
            for company_id in sorted({l.target_id for l in db.scalars(stmt).all()})]
    if group:
        features['accessible_group_size'] = feature(len(group), 'GROUP_ID; только доступные пользователю компании', 'calculated', 'Доступные участники группы')
    missing = [label for key, label in [("REVENUE_COMPANY", "Выручка"), ("MAINOKVED_CODE", "ОКВЭД"), ("FTS_COUNTRY_NAME", "Страны из данных ФТС")]
               if value(company, key) is None]
    return {"id": company.id, "name": company.name, "industry": company.industry,
            "region": company.region, "synthetic": company.synthetic, "features": features,
            "products": [label for key, label in PRODUCTS.items() if value(company, key) is True],
            "group": group, "counterparties": related, "shared_person_links": shared_person_links,
            "missing": missing + ["Рыночная доля: нет данных об объеме рынка", "Суммы, ставки и сроки кредитов", "Направление внешней торговли и валюты контрактов", "Единицы выручки и сумм платежей из CSV не подтверждены"],
            "payment_summary": {"incoming": sum(p.amount or 0 for p in incoming), "outgoing": total,
                "self_payments": sum(p.amount or 0 for p in self_payments)},
            "limitations": ["Платежи описывают только предоставленный набор; период и полнота требуют проверки.",
                            "Платежи компании самой себе исключены из числа контрагентов и концентрации внешних платежей.",
                            "Город регистрации не доказывает географию всех операций."]}
