"""Deterministic evidence checks, usable in offline replay without the LLM gateway."""
import re
from datetime import datetime
from decimal import Decimal
from .cashflow import cashflow_issues
from .forecast import price_forecast_issues

def numeric_values(text):
    # Compare full numeric values, never substrings (10 is not confirmed by 100).
    pattern = (r"(?<!\w)([+−-]?\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?)"
               r"(?:\s*(тыс(?:\.|яч(?:а|и|у|ей|ам|ами|ах)?)?|млн\.?|миллион(?:а|ов)?|млрд\.?|миллиард(?:а|ов)?|трлн\.?)\b\.?)?")
    values = set()
    for match in re.finditer(pattern, text, flags=re.I):
        value, scale = match.groups()
        number = Decimal(re.sub(r"[ \u00a0\u202f]", "", value).replace(",", ".").replace("−", "-"))
        scale = (scale or '').lower()
        factor = (1000 if scale.startswith('тыс') else 1_000_000 if scale.startswith(('млн', 'миллион'))
                  else 1_000_000_000 if scale.startswith(('млрд', 'миллиард')) else 1_000_000_000_000 if scale.startswith('трлн') else 1)
        values.add(number * factor)
    return values


def dated_numbers(text):
    """Separate complete dates from quantities: a publication day cannot prove a rate."""
    dates = set()
    months = {'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
              'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12}
    month_forms = dict(months)
    month_forms.update({word: i for i, words in enumerate([
        'январь январе', 'февраль феврале', 'март марте', 'апрель апреле', 'май мае', 'июнь июне',
        'июль июле', 'август августе', 'сентябрь сентябре', 'октябрь октябре', 'ноябрь ноябре', 'декабрь декабре'], 1)
        for word in words.split()})
    def replace(match):
        raw = match.group()
        try:
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw):
                day = datetime.strptime(raw, '%Y-%m-%d').date()
            elif re.fullmatch(r'\d{1,2}\.\d{1,2}\.\d{4}', raw):
                day = datetime.strptime(raw, '%d.%m.%Y').date()
            else:
                parts = raw.lower().split()
                if len(parts) == 2:
                    if parts[0] in month_forms:
                        dates.add(f'{int(parts[1]):04}-{month_forms[parts[0]]:02}')
                    else:
                        dates.add(parts[0])  # Explicit year with «год/года/г.».
                    return ';'
                d, month, y = parts
                day = datetime(int(y), months[month], int(d)).date()
            dates.add(day.isoformat())
            return ';'
        except (ValueError, KeyError):
            return raw
    pattern = (r'(?<!\w)(?:\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}\s+(?:' + '|'.join(months)
        + r')\s+\d{4}|(?:' + '|'.join(month_forms) + r')\s+\d{4}|\d{4}\s+(?:года|году|год|г\.))(?!\w)')
    without_dates = re.sub(pattern, replace, text, flags=re.I)
    # A range separator must not turn 91–180 into a space-grouped number 91 180.
    without_dates = re.sub(r'(?<=\d)[–—-](?=\d)', ';', without_dates)
    return numeric_values(without_dates), dates


def model_grounds(evidence):
    """Short request-local citations avoid copying opaque database identifiers."""
    aliases = {f'E{i + 1}': e['id'] for i, e in enumerate(evidence)}
    groups = {key: f'D{i + 1}' for i, key in enumerate(dict.fromkeys(e.get('document_id', e['id'].rsplit(':', 1)[0]) for e in evidence))}
    sources = [{**{k: v for k, v in e.items() if k not in ('id', 'document_id')}, 'id': alias,
                'document_group': groups[e.get('document_id', e['id'].rsplit(':', 1)[0])]}
               for alias, e in zip(aliases, evidence)]
    return sources, aliases


def restore_citations(insight, aliases):
    restored = insight.model_copy(deep=True)
    for section in ('facts', 'bank_view', 'impact', 'risks', 'opportunities', 'actions', 'answer'):
        for claim in getattr(restored, section):
            # Unknown references stay unknown and must fail validation.
            claim.evidence_ids = [aliases.get(ref, ref) for ref in claim.evidence_ids]
    return restored


def claim_features(insight, context):
    return {section: [{key: context['features'][key] for key in claim.feature_keys
                       if key in context['features']} for claim in getattr(insight, section)]
            for section in ('facts', 'bank_view', 'impact', 'risks', 'opportunities', 'actions', 'answer')}


def validate_insight(insight, evidence, context, event_source_ids=None):
    known = {e["id"]: e for e in evidence}
    issues = []
    for section in ("facts", "bank_view", "impact", "risks", "opportunities", "actions", "answer"):
        for index, claim in enumerate(getattr(insight, section)):
            item_id = f'{section}.{index}'
            if section in ('impact', 'risks', 'opportunities', 'actions', 'answer'):
                issues.extend(f'{item_id}: {issue}' for issue in cashflow_issues(claim.text))
                issues.extend(f'{item_id}: {issue}' for issue in price_forecast_issues(claim.text))
            if any(ref not in known for ref in claim.evidence_ids):
                issues.append(f"{item_id}: неизвестная ссылка на источник")
            if any(key not in context["features"] for key in claim.feature_keys):
                issues.append(f"{item_id}: неизвестный признак клиента")
            if not claim.evidence_ids and not claim.feature_keys and not claim.assumption:
                issues.append(f"{item_id}: утверждение без источника")
            if section in ('impact', 'risks', 'opportunities', 'actions') and not claim.assumption:
                issues.append(f'{item_id}: аналитический вывод или предложение должно иметь assumption=true')
            if section in ('facts', 'bank_view') and claim.assumption:
                issues.append(f'{item_id}: факт и позиция банка не могут обходить проверку меткой предположения')
            if section == 'facts' and event_source_ids is not None and (not claim.evidence_ids or not set(claim.evidence_ids).issubset(event_source_ids)):
                issues.append(f'{item_id}: факты события должны ссылаться на исходные новости этого события')
            if section == "bank_view" and (not claim.evidence_ids or any(known.get(ref, {}).get("kind") != "bank" for ref in claim.evidence_ids)):
                issues.append(f"{item_id}: Позиция банка должна опираться только на банковские материалы")
            if any(known.get(ref, {}).get('relevance', {}).get('level') == 'irrelevant' for ref in claim.evidence_ids):
                issues.append(f'{item_id}: источник не связан с предметом события')
            if (section in ('impact', 'risks', 'opportunities', 'actions') or section == 'answer' and claim.assumption) and any(
                known.get(ref, {}).get('relevance', {}).get('level') == 'background' for ref in claim.evidence_ids):
                issues.append(f'{item_id}: фоновая аналитика смежной отрасли не подтверждает персональное последствие или рекомендацию; нужны применимые основания')
            if section in ("facts", "bank_view", "answer") and not claim.assumption:
                source_text = " ".join(known.get(ref, {}).get("excerpt", "") for ref in claim.evidence_ids)
                source_numbers, source_dates = dated_numbers(source_text)
                for ref in claim.evidence_ids:
                    date = known.get(ref, {}).get('published_at')
                    if date:
                        try:
                            published = datetime.fromisoformat(date.replace('Z', '+00:00'))
                            source_dates.add(published.date().isoformat())
                        except ValueError:
                            pass
                if section in ('facts', 'answer'):
                    source_numbers |= numeric_values(' '.join(str(context['features'].get(key, {}).get('value', '')) for key in claim.feature_keys))
                numbers, dates = dated_numbers(claim.text)
                source_dates |= {part for date in list(source_dates) for part in (date[:4], date[:7])}
                if not numbers.issubset(source_numbers):
                    issues.append(f"{item_id}: число отсутствует в цитируемом фрагменте")
                if not dates.issubset(source_dates):
                    issues.append(f'{item_id}: дата отсутствует в цитируемом фрагменте и метаданных')
    if not insight.impact:
        issues.append("Нет интерпретации влияния на компанию")
    for index, text in enumerate(insight.limitations):
        issues.extend(f'limitations.{index}: {issue}' for issue in price_forecast_issues(text))
    for index, claim in enumerate(insight.bank_view):
        direct_ids = {ref for ref in claim.evidence_ids
                      if known.get(ref, {}).get('relevance', {}).get('level') not in ('background', 'irrelevant')}
        applied = any(direct_ids.intersection(c.evidence_ids) for c in insight.impact + insight.risks + insight.opportunities)
        if direct_ids and not applied:
            issues.append(f'bank_view.{index}: прямая позиция банка не связана с последствиями; покажите подтверждённый механизм в impact/risks/opportunities либо исключите неприменимый тезис')
    return list(dict.fromkeys(issues))
