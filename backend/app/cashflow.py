"""High-precision checks for invalid budget-to-cash implications, not an NLP verifier.

The same rules guard generation and a positive model verdict. Independent conditions
and explicit denials are kept separate from claims that money follows from a budget.
"""
import re

VALIDATION_VERSION = 'financial-v3'

FINANCIAL_LOGIC = """Проверяй каждое звено финансового вывода, даже внутри «если» и при assumption=true.
Наличие кредитных продуктов и лизинга не доказывает, что компания уже внесла платежи в календарь. Не утверждай «поэтому календарь уже включает обязательства»; рекомендуй проверить полноту календаря и учесть платежи. Общая рекомендация о размещении остатка не становится возможностью от новости, если связь с событием не установлена: раздел opportunities можно оставить пустым.
Расходы в пределах/на уровне бюджета означают только отсутствие перерасхода: это не экономия и не новые деньги.
Экономия требует отдельного сравнения с базой при сопоставимых объёме, цене и условиях расчётов. Даже подтверждённая экономия расходов не доказывает свободный денежный остаток: нужны поступления, сроки обязательств, ограничения и резерв ликвидности.
Пример ошибки: «Если платежи останутся в бюджете, высвободившийся остаток можно разместить». Условие не влечёт следствие; метка сценария и отсутствие депозитного продукта это не исправляют.
Допустимо: «Сверить платежи с планом. Если платёжный календарь после обязательств и резерва подтвердит свободный остаток, запросить условия размещения». Здесь наличие остатка — самостоятельное условие, а не следствие соблюдения бюджета.
Не выводи направление цены конкретного товара из достаточности выпуска или возобновления экспорта без оснований. Внешнее событие, экономия расходов и доступность денег — разные переходы, каждый требует доказательства либо самостоятельного явного условия."""

_WITHIN_PLAN = re.compile(
    r'(?:соблюд\w*\s+(?:\w+\s+){0,2}(?:бюджет|план)\w*'
    r'|(?:бюджет|план)\w*\s+(?:\w+\s+){0,2}соблюд\w*'
    r'|(?:остан\w*|остал\w*|остать\w*|укладыва\w*|улож\w*|впис\w*)\s+(?:\w+\s+){0,3}в\s+(?:(?:пределах|рамках)\s+)?(?:бюджет|план|смет)\w*'
    r'|в\s+(?:пределах|рамках)\s+(?:\w+\s+){0,2}(?:бюджет|план|смет|лимит)\w*'
    r'|не\s+(?:превы\w*|выйд\w*\s+за)\s+(?:\w+\s+){0,2}(?:бюджет|план|смет|лимит)\w*'
    r'|(?:на\s+уровне|вблизи|около)\s+(?:бюджет|план)\w*'
    r'|без\s+перерасход\w*)')
_CASH = re.compile(
    r'(?:высвобо(?:д|ж)\w*|освобо(?:д|ж)\w*)\s+(?:\w+\s+){0,3}(?:остат\w*|средств\w*|деньг\w*|ликвидност\w*)'
    r'|(?:деньг\w*|средств\w*)\s+(?:\w+\s+){0,2}(?:высвобо(?:д|ж)\w*|освобо(?:д|ж)\w*)'
    r'|свободн\w*\s+(?:денежн\w*\s+)?(?:остат\w*|средств\w*|деньг\w*|ликвидност\w*)'
    r'|излиш\w*\s+(?:денег|средств|ликвидност\w*)')
_SAVING = re.compile(r'экономи[яиюей]\w*|сэконом\w*')
_DENIAL = re.compile(
    r'не\s+(?:означа\w*|доказыва\w*|гарантир\w*|подтвержда\w*|созда\w*|обеспеч\w*|да[ею]т|вед[еуы]\w*)'
    r'|не\s+(?:следует|счита\w*|вывод\w*)|нельзя\s+(?:считать|выводить|заключать)|недостаточ\w*\s+для')


def _independent_or_denied(text, start, end, premise_end):
    # Scope exceptions to the outcome clause: a disclaimer elsewhere is not a waiver.
    boundary = max(text.rfind(mark, premise_end, start) for mark in (',', ';', '.', '!', '?'))
    prefix = text[max(boundary + 1, premise_end):start]
    suffix = re.split(r'[,;.!?]', text[end:])[0]
    clause_start = max(text.rfind(mark, 0, start) for mark in (',', ';', '.', '!', '?')) + 1
    if _DENIAL.search(text[clause_start:start]) or re.match(r'\s+не\s+(?:возник\w*|появ\w*|образ\w*|высвоб\w*|гарантир\w*|подтвержд\w*)', suffix):
        return True
    # A new if/when condition belongs to the cash outcome, not to the earlier budget.
    if re.search(r'(?:если\s*|при\s+(?:наличии|подтвержден\w*|устойчив\w*)\s+)$', prefix):
        return True
    if re.search(r'(?:если|при\s+условии|календар\w*|расчет\w*)\b[^;.!?]*'
                 r'(?:подтвер\w*|покаж\w*|показыва\w*|есть|имеется)\s+(?:\w+\s+){0,3}$', prefix):
        return True
    if re.search(r'(?:и|а)\s+(?:есть|имеется|подтвержден\w*)\s+(?:\w+\s+){0,3}$', prefix):
        return True
    if re.search(r'(?:провер\w*|выясн\w*|уточн\w*|подтвер\w*)\s+(?:наличие\s+)?$', prefix):
        return True
    if re.search(r'(?:есть|имеется|появится)\s+ли\s+(?:\w+\s+){0,3}$', prefix):
        return True
    if re.match(r'\s+подтвержд\w*\s+(?:расчет\w*|календар\w*)', suffix):
        return True
    return False


def _unsupported_link(text, premise, outcome):
    if outcome.start() >= premise.end():
        return not _independent_or_denied(text, outcome.start(), outcome.end(), premise.end())
    if outcome.end() > premise.start():
        return False
    link = text[outcome.end():premise.start()]
    return (bool(re.search(r'потому\s+что|так\s+как|поскольку|благодаря|за\s+счет', link))
            and not _DENIAL.search(link)
            and not _independent_or_denied(text, outcome.start(), outcome.end(), 0))


def cashflow_issues(text):
    text = ' '.join(text.lower().replace('ё', 'е').split())
    findings = []
    if re.search(r'(?:поэтому|значит|следовательно)\s+(?:платежн\w*\s+)?календар\w*\s+(?:уже\s+)?(?:включает|учитывает|предусматривает)', text):
        findings.append('Наличие обязательств не доказывает их фактический учёт в платёжном календаре. '
                        'Рекомендуйте проверить полноту календаря; его содержимое в данных не предоставлено.')
    for premise in _WITHIN_PLAN.finditer(text):
        for outcome in sorted([*_CASH.finditer(text), *_SAVING.finditer(text)], key=lambda m: m.start()):
            if not _unsupported_link(text, premise, outcome):
                continue
            # A separate explicit below-plan comparison can establish savings, never cash availability.
            if _SAVING.fullmatch(outcome.group()) and re.search(r'(?:ниже|меньше)\s+(?:плана|плановых|бюджета)', text[premise.end():outcome.start()]):
                continue
            findings.append('Соблюдение бюджета не доказывает экономию или свободный остаток. '
                'Не выводите высвобождение денег из отсутствия перерасхода; отдельно проверьте поступления, обязательства и резерв ликвидности.')
            break
    # An expense saving and cash available for placement are distinct measurements.
    for premise in _SAVING.finditer(text):
        clause_start = max(text.rfind(mark, 0, premise.start()) for mark in (',', ';', '.', '!', '?')) + 1
        if _DENIAL.search(text[clause_start:premise.start()]):
            continue
        for outcome in _CASH.finditer(text):
            if _unsupported_link(text, premise, outcome):
                findings.append('Экономия расходов сама по себе не доказывает доступный для размещения остаток. '
                    'Нужно отдельное условие подтверждения остатка платёжным календарём после обязательств и резерва.')
                break
    return list(dict.fromkeys(findings))


def financial_findings(items):
    findings = {}
    for item_id, item in items.items():
        if item_id.split('.')[0] in ('impact', 'risks', 'opportunities', 'actions', 'answer'):
            issues = cashflow_issues(item['text'])
            if issues:
                findings[item_id] = issues
    return findings
