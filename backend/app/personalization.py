"""Mechanism-first ranking. Topic, geography and freshness alone grant no exposure."""
from .db import utcnow
from .news_focus import match

RANKING_VERSION = 'mechanism-focus-v3'


def rank(event, context, role, *, as_of=None):
    text = getattr(event, 'focus_text', None) or event.title
    industry = context['industry']
    features = context['features']
    has = lambda key: features.get(key, {}).get('value') is True
    freight = match(r'перевоз|грузов\w* транспорт|логист|транспортиров', industry)
    pharma = match(r'фармацев|лекарств', industry)
    metal = match(r'металл|стал[ьи]|металлоконструк', industry)
    retail = match(r'рознич', industry)
    production = match(r'производ|обрабатыва', industry)
    trading = match(r'торгов', industry)
    mechanism = []

    def add(points, reason, key, topic, level='indirect'):
        points = points[role] if isinstance(points, dict) else points
        if points > 0:
            mechanism.append((points, reason, key, topic, level))

    private_incident = match(r'\b(?:мошенник|обвиняем|арестова|погиб|теракт|концерт|наград|протест|убийств|дипмисси|посольств|посол\b|выбор\w* генсек|беспилотник|бпла|военн\w* помощ)', text)
    rate_policy = match(r'ключев\w*\s+став', text)
    corporate = match(r'(?:корпоративн\w*|бизнес\w*|предприяти\w*|компани\w*).{0,45}(?:кредитован|финансирован|ставк)|(?:ставк|кредитован).{0,45}(?:бизнес|корпоратив)', text)
    retail_rates = match(r'вклад|депозит', text) and match(r'физическ\w*\s+лиц|населен|розничн|социальн\w*\s+вклад', text)
    if not private_incident and (rate_policy or corporate):
        if has('CL_PRODUCT_LOA_MARK'):
            add({'CEO':34,'CFO':52,'TREASURER':40}, 'Условия финансирования связаны с отмеченными кредитными продуктами; сроки и ставки договоров неизвестны.', 'CL_PRODUCT_LOA_MARK', 'rates', 'direct')
        if has('CL_PRODUCT_DEP_MARK'):
            add({'CEO':18,'CFO':26,'TREASURER':32}, 'Процентная среда важна для депозитных продуктов; актуальный остаток и котировки не установлены.', 'CL_PRODUCT_DEP_MARK', 'rates', 'direct')
        if not has('CL_PRODUCT_LOA_MARK') and not has('CL_PRODUCT_DEP_MARK'):
            add({'CEO':16,'CFO':26,'TREASURER':22}, 'Процентная среда — фон планирования бизнеса, а не известные условия его договоров.', 'MAINOKVED_NAME', 'rates')
    elif retail_rates and match(r'ставк|ставок|доходност', text) and not match(r'социальн\w*\s+вклад',text) and not private_incident and (has('CL_PRODUCT_LOA_MARK') or has('CL_PRODUCT_DEP_MARK')):
        add({'CEO':0,'CFO':20,'TREASURER':24}, 'Розничные ставки дают только рыночный фон; они не являются корпоративными котировками.', 'CL_PRODUCT_DEP_MARK' if has('CL_PRODUCT_DEP_MARK') else 'CL_PRODUCT_LOA_MARK', 'rates')

    if not private_incident and match(r'инфляци|рост\w*\s+(?:потребительск\w*\s+)?цен|потребительск\w*\s+цен', text) and match(r'\b(?:рф|росси\w*|цб|росстат|набиуллин\w*)\b', text):
        add({'CEO':24,'CFO':28,'TREASURER':18}, 'Российская инфляция — сценарный фон затрат и оборотного капитала; эффект для компании требует её договоров.', 'MAINOKVED_NAME', 'demand')

    forex = match(r'курс\w*\s+(?:рубл|доллар|евро|юан)|(?:рубл\w*|доллар\w*|юан\w*|евро).{0,25}(?:курс|подорож|подешев|укреп|ослаб)|валютн\w*\s+(?:расчет|платеж|контрол)', text)
    cross_payments = match(r'трансграничн\w*\s+(?:платеж|расчет)|расчет\w*\s+с\s+зарубежн|банк\w*-корреспондент', text)
    if has('FTS_FLAG') and not private_incident and (forex or cross_payments):
        add({'CEO':22,'CFO':30,'TREASURER':34}, 'Есть сведения ФТС; валюты и направления сделок неизвестны. Нужно проверить применимость валютных условий или сроков расчётов.', 'FTS_FLAG', 'fx')

    countries = str(features.get('FTS_COUNTRY_NAME', {}).get('value') or '')
    country_patterns = {'КИТАЙ':r'кита[йяею]|китайск', 'ИНДИЯ':r'инди[яиюе]|индийск',
                        'ЮЖНАЯ КОРЕЯ':r'южн\w* коре|южнокорейск', 'БАНГЛАДЕШ':r'бангладеш'}
    matched_countries = [name for name, pattern in country_patterns.items() if name in countries.upper() and match(pattern, text)]
    trade_change = match(r'пошлин|таможен|экспортн\w*\s+(?:ограничен|пошлин)|импортн\w*\s+(?:ограничен|пошлин)|трансгранич|торгов\w*\s+(?:расчет|ограничен|соглашен)|работ\w*\s+.{0,35}банк', text)
    if matched_countries and trade_change and not private_incident:
        add({'CEO':26,'CFO':28,'TREASURER':30}, 'Страна из сведений ФТС: ' + ', '.join(matched_countries) + '. Товары, направление торговли и действующие контракты нужно уточнить.', 'FTS_COUNTRY_NAME', 'fx')

    if pharma and match(r'фарм|лекарств|медикамент|препарат|вакцин|\bгрипп|\bорви|онколог', text) and not private_incident:
        if match(r'сертификат|\bgmp\b',text):
            add({'CEO':18,'CFO':0,'TREASURER':0}, 'Сертификация производителя — фон выбора ассортимента и поставщиков; связь с ним и контракты компании неизвестны.', 'MAINOKVED_NAME', 'demand')
        elif match(r'клиническ\w*\s+(?:исследован|эффективност|испытан)|исследован\w*\s+препарат',text):
            add({'CEO':18,'CFO':0,'TREASURER':0}, 'Исследование может повлиять на будущий ассортимент. Оно не означает регистрации показаний, доступности препарата или текущего спроса.', 'MAINOKVED_NAME', 'demand')
        elif match(r'вакцин|грипп|орви|заболеваемост|спрос|цен\w*\s+на\s+(?:лекарств|препарат)|правил\w*\s+(?:допуска|обращения)',text):
            add({'CEO':52,'CFO':32,'TREASURER':24}, 'Событие касается фармацевтического спроса или обращения препаратов; ассортимент и заказы компании неизвестны.', 'MAINOKVED_NAME', 'demand', 'direct')
        elif match(r'завод|производств|зарегистрир|выпуск',text):
            add({'CEO':26,'CFO':18,'TREASURER':0}, 'Развитие выпуска лекарств — фон планирования ассортимента и закупок. Сроки доступности, поставщик и заказы компании нужно подтвердить.', 'MAINOKVED_NAME', 'demand')
    steel = match(r'\bсталь\b|(?:рынок|цен\w*|производств\w*|выпуск\w*|экспорт\w*|импорт\w*|поставк\w*|спрос\w*)(?:\s+на)?\s+стали\b|сталелит|металлопрокат|металлоконструк|промышленн\w*\s+металл|цен\w*\s+на\s+металл|черн\w*\s+металл', text)
    if metal and steel and not private_incident:
        add({'CEO':48,'CFO':38,'TREASURER':24}, 'Предмет связан с производством металлопродукции; состав сырья, объёмы и формулы цен требуют проверки.', 'MAINOKVED_NAME', 'commodities', 'direct')
    if retail and match(r'розничн\w*\s+(?:спрос|торговл|продаж)|потребительск\w*\s+спрос', text) and not private_incident:
        add({'CEO':48,'CFO':32,'TREASURER':22}, 'Изменение потребительского спроса связано с розничной деятельностью; категории товаров необходимо сопоставить.', 'MAINOKVED_NAME', 'demand', 'direct')
    industrial_outlook = match(r'роботизац|производительност\w*\s+труда|восстановлен\w*\s+(?:выбывших\s+)?производственн\w*\s+мощност', text)
    if production and industrial_outlook and match(r'росси|\bрф\b|госсовет',text) and not private_incident:
        add({'CEO':24,'CFO':20,'TREASURER':0}, 'Промышленный прогноз или программа важны для планирования производства; доступность мер и эффект для предприятия не установлены.', 'MAINOKVED_NAME', 'demand')

    fuel = match(r'дизел|бензин|топлив|\bгсм\b', text)
    fuel_market = match(r'цен|экспорт|выпуск|дефицит|рынок|нехват|производств|поставк', text)
    if freight and has('CL_PRODUCT_LEA_MARK') and match(r'автолизинг',text) and match(r'льгот|программ',text):
        add({'CEO':24,'CFO':28,'TREASURER':0}, 'Программа автолизинга потенциально связана с деятельностью перевозчика и отметкой лизинга; предмет договоров, планы обновления и право на льготу неизвестны.', 'CL_PRODUCT_LEA_MARK', 'rates')
    foreign_fuel_market = match(r'\bес\b|евросоюз|европ|франц|британ|серби', event.title) and not match(r'росси|\bрф\b',event.title)
    if freight and fuel and fuel_market and not private_incident and not foreign_fuel_market:
        add({'CEO':26,'CFO':30,'TREASURER':28}, 'Топливо может влиять на затраты перевозчика; парк, договоры и самостоятельные закупки неизвестны.', 'MAINOKVED_NAME', 'commodities')
    freight_change = match(r'(?:грузов\w*|перевозчик|логистик|логистическ|перевозк).{0,60}(?:тариф|срок|доставк|ограничен|правил|стоимост|требован|подорож|затрат)|(?:тариф|срок|правил|стоимост).{0,40}(?:перевоз|достав|груз)', text)
    freight_incident = match(r'логистическ\w*\s+центр|грузов\w*\s+терминал', text) and match(r'пожар|атак|приостанов|перенаправ|закры', text)
    if freight_change and not private_incident:
        if freight:
            add({'CEO':42,'CFO':34,'TREASURER':28}, 'Изменились условия грузовых перевозок; нужно проверить маршруты и действующие договоры компании.', 'MAINOKVED_NAME', 'logistics', 'direct')
        elif production or trading:
            add({'CEO':16,'CFO':20,'TREASURER':18}, 'Изменение сроков или стоимости грузовой доставки может затронуть снабжение; маршруты компании неизвестны.', 'MAINOKVED_NAME', 'logistics')
    elif freight and freight_incident:
        add({'CEO':18,'CFO':0,'TREASURER':0}, 'Нарушение работы грузового объекта: стоит проверить маршруты. Связь компании с этим объектом не установлена.', 'MAINOKVED_NAME', 'logistics')

    business_rule = match(r'(?:налог|отчетност|регулирован|правил\w*\s+расчет|требован).{0,65}(?:организац|компани|бизнес|предприяти)|(?:бизнес|организац|компани|предприяти).{0,65}(?:налог|отчетност|регулирован)|\bндс\b|налог\w*\s+на\s+прибыл', text)
    # Individual cases, taxes of individuals and regulations of unrelated industries
    # do not become economy-wide business rules merely through a keyword match.
    narrow_audience = match(r'физическ\w*\s+лиц|ипиф|паев\w*\s+фонд|онлайн-казино|(?:небанковск\w*\s+)?кредитн\w*\s+организац', text)
    if business_rule and not private_incident and not narrow_audience:
        add({'CEO':30,'CFO':38,'TREASURER':26}, 'Изменение правил для бизнеса требует проверки применимости к налоговому режиму и операциям компании.', 'MAINOKVED_NAME', 'regulation')
    if not private_incident and match(r'ликвидност|платежн\w*\s+календар|срок\w*\s+(?:межбанковск\w*\s+)?платеж|систем\w*\s+быстр\w*\s+платеж', text) and has('CL_PRODUCT_RKO_MARK'):
        add({'CEO':18,'CFO':32,'TREASURER':48}, 'Сроки расчётов и ликвидность связаны с РКО; конкретные обязательства проверяются по календарю.', 'CL_PRODUCT_RKO_MARK', 'liquidity', 'direct')
    if has('CL_PRODUCT_ZPP_MARK') and match(r'нспк|национальн\w*\s+систем\w*\s+платежн\w*\s+карт',text) and match(r'тариф',text):
        add({'CEO':0,'CFO':18,'TREASURER':22}, 'Тарифы карточной инфраструктуры — косвенный фон зарплатного проекта; условия компании и перенос тарифов банком неизвестны.', 'CL_PRODUCT_ZPP_MARK', 'liquidity')
    if not private_incident and match(r'дефицит\w*\s+кадр|рост\w*\s+зарплат|рынок\w*\s+труд', text) and (production or freight):
        add({'CEO':28,'CFO':20,'TREASURER':0}, 'Изменение рынка труда может влиять на кадровый план и расходы; штат и ставки оплаты неизвестны.', 'MAINOKVED_NAME', 'labor')

    if not mechanism:
        note = 'Применимый механизм влияния по имеющемуся профилю не установлен. Совпадения темы или региона недостаточно.'
        return {'score':0.0,'eligible':False,'reasons':[note],'feature_keys':[], 'topics':[],
                'exposure':{'level':'unknown','note':note},'ranking_version':RANKING_VERSION}
    # Independent mechanisms do not accumulate without bound (one rate story can
    # mention loans, deposits and inflation). Freshness is only a tie-breaker.
    points = sorted((m[0] for m in mechanism), reverse=True)
    direct = any(m[4] == 'direct' for m in mechanism)
    age = max(((as_of or utcnow()) - event.published_at).total_seconds()/86400, 0)
    score = points[0] + min(sum(points[1:])*.15, 8) + max(0, 5-age/7)
    note = ('Связь с признаком профиля подтверждена; финансовый эффект не рассчитан.' if direct else
            'Косвенный механизм; реальные операции, объёмы и сроки нужно подтвердить.')
    return {'score':round(min(score, 90 if direct else 39),1),'eligible':True,
            'reasons':list(dict.fromkeys(m[1] for m in mechanism)),
            'feature_keys':list(dict.fromkeys(m[2] for m in mechanism)),
            'topics':list(dict.fromkeys(m[3] for m in mechanism)),
            'exposure':{'level':'direct' if direct else 'indirect','note':note},'ranking_version':RANKING_VERSION}
