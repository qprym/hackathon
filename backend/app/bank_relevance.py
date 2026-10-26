"""Conservative, inspectable subject matching; no model or network calls."""
import re

SEARCH_VERSION = 'bank-sections-v2'

# Match subjects, not publication names. A gold report can contain a useful fuel
# paragraph; its title alone can neither admit nor veto that paragraph.
SUBJECTS = {
    'diesel': (r'\bдизел\w*', 'energy'),
    'gasoline': (r'\bбензин\w*', 'energy'),
    'oil': (r'\b(?:нефт\w*|нпз)\b', 'energy'),
    'fuel': (r'\b(?:топлив\w*|гсм)\b', 'energy'),
    'gas': (r'\b(?:газ|газа|газу|газом|газе|газов\w*|спг)\b', 'gas'),
    'gold': (r'\bзолот\w*', 'precious_metals'),
    'silver': (r'\bсеребр\w*', 'precious_metals'),
    'steel': (r'\b(?:сталь|стали|сталью|стале\w*|черн\w*\s+металл\w*)\b', 'steel'),
    'grain': (r'\b(?:зерн\w*|пшениц\w*)\b', 'grain'),
    'deposit_rates': (r'\b(?:депозит\w*|вклад(?:ы|ов|ам|ах|а|у|ом)?)(?:\s|[.,;:]|$)', 'interest_rates'),
    'policy_rate': (r'\bключев\w*\s+став(?:к\w*|ок)', 'interest_rates'),
    'interest_rates': (r'\b(?:ставк\w*|ставок)\b', 'interest_rates'),
}
STOP_WORDS = set('банк банки банка россии российский российская российские страна рынок рынки рынках обзор аналитика новости новость заявил заявила оценил оценила возможность глава набиуллина эльвира альфа ведомости источник материал мнению также который которые может могут будет будут этого чтобы достаточно общий сырьевые экспорт внешняя торговля результаты результат максимальных мониторинга'.split())


def words(text):
    stems = ('ставк', 'кредит', 'депозит', 'инфляц', 'ликвид', 'логист', 'перевоз', 'транспорт', 'платеж', 'потреблен')
    return {next((stem for stem in stems if word.startswith(stem)), word[:7])
            for word in re.findall(r'[а-яёa-z]{4,}', text.casefold().replace('ё', 'е'))
            if word not in STOP_WORDS}


def subjects(text):
    found = {name for name, (pattern, _) in SUBJECTS.items() if re.search(pattern, text, re.I)}
    if found & {'policy_rate', 'deposit_rates'}:
        found.discard('interest_rates')
    return found


def subject_match(focus, body):
    requested = subjects(focus)
    if not requested:
        return None  # Caller applies lexical matching for non-commodity events.
    found = subjects(body)
    exact = requested & found
    if exact:
        return {'level': 'direct', 'matched_subjects': sorted(exact),
                'reason': 'Во фрагменте упомянут предмет новости; применимость тезиса проверяется отдельно.'}
    families = {SUBJECTS[name][1] for name in requested}
    adjacent = {name for name in found if SUBJECTS[name][1] in families}
    if adjacent:
        # Incidental oil mentions inside a predominantly gold/currency paragraph
        # do not make it evidence about diesel supply. Keep genuinely mixed
        # passages when they discuss the exact requested subject (handled above).
        unrelated = found - adjacent
        adjacent_mentions = sum(len(re.findall(SUBJECTS[name][0], body, re.I)) for name in adjacent)
        other_mentions = sum(len(re.findall(SUBJECTS[name][0], body, re.I)) for name in unrelated)
        if unrelated and other_mentions >= adjacent_mentions:
            return {'level':'irrelevant', 'matched_subjects':[],
                    'reason':'Смежный предмет упомянут попутно; основной предмет фрагмента относится к другой теме.'}
        return {'level': 'background', 'matched_subjects': sorted(adjacent),
                'reason': 'Смежная тема: исторический фон, не оценка конкретного предмета новости или последствий для клиента.'}
    return {'level': 'irrelevant', 'matched_subjects': [],
            'reason': 'Во фрагменте нет предмета новости или смежного отраслевого основания.'}
