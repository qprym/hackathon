"""Compose a reading list from checked model grades, without reclassifying news.

No article keywords, company IDs or evaluation labels affect this policy.
The bounded diversity rule is an OFFLINE experiment. Serving uses balance=False
and a separate, reviewed listwise model selection when its exact cache exists.
Raw model scores/evidence stay intact. Historical editions are presentation
groups, never assertions that different releases describe the same event.
"""
import re
from datetime import datetime, timezone
from .event_groups import diversified

ORDERING_VERSION = 'reading-list-v1'
FINANCIAL_AXES = frozenset({'rates', 'fx', 'liquidity'})
REPEAT_FACTOR = 2 / 3


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def score_order(entry):
    return (entry['score'], timestamp(entry['published_at']), entry['title'].casefold(), entry['id'])


def edition_family(entry):
    """Require an exact publisher/heading and a valid explicit publication date."""
    match = re.fullmatch(r'(.{24,}?)\s*\((\d{2}\.\d{2}\.\d{4})\)', entry['title'].strip())
    if not match or not entry.get('publisher') or entry.get('exposure', {}).get('level') != 'indirect':
        return None
    try:
        if datetime.strptime(match[2], '%d.%m.%Y').date() != timestamp(entry['published_at']).date():
            return None
    except ValueError:
        return None
    return (entry['publisher'].casefold().strip(), ' '.join(match[1].casefold().split()))


def fold_editions(entries):
    families = {}
    result = []
    for entry in entries:
        family = edition_family(entry) if entry.get('eligible') else None
        if family is None:
            result.append(dict(entry))
        else:
            families.setdefault(family, []).append(entry)
    for editions in families.values():
        editions.sort(key=lambda e: (timestamp(e['published_at']), *score_order(e)), reverse=True)
        latest = dict(editions[0])
        latest['previous_editions'] = [
            {k: e.get(k) for k in ('id', 'title', 'published_at', 'document_id', 'publisher', 'score')}
            for e in editions[1:]
        ]
        result.append(latest)
    return result


def assemble_feed(entries, *, role='CFO', compact_series=True, balance=True):
    """Bound repeated financial background to 2/3 of its model priority.

    High-priority direct links stay above indirect scenarios. The bounded factor
    never changes eligibility or inserts an article to satisfy a topic quota.
    This changes list order, never eligibility, model scores or validation.
    """
    if role not in ('CEO', 'CFO', 'TREASURER'):
        raise ValueError('Unknown reading-list role')
    pending = diversified(sorted(entries, key=score_order, reverse=True))
    if compact_series:
        pending = fold_editions(pending)
    result = []
    covered = set()
    while pending:
        def priority(entry):
            eligible = bool(entry.get('eligible'))
            strong = eligible and entry.get('exposure', {}).get('level') == 'direct'
            repeated = covered & set(entry.get('topics', [])) & FINANCIAL_AXES
            factor = REPEAT_FACTOR if balance and role != 'TREASURER' and eligible and not strong and repeated else 1
            return (eligible, strong, entry['score'] * factor, *score_order(entry))
        chosen = max(pending, key=priority)
        pending.remove(chosen)
        entry = dict(chosen)
        repeated = sorted(covered & set(entry.get('topics', [])) & FINANCIAL_AXES)
        strong = entry.get('exposure', {}).get('level') == 'direct'
        penalized = bool(balance and role != 'TREASURER' and entry.get('eligible') and not strong and repeated)
        entry['ordering'] = {
            'version': ORDERING_VERSION,
            'role': role,
            'model_score': entry['score'],
            'list_priority': round(entry['score'] * (REPEAT_FACTOR if penalized else 1), 4),
            'repeated_financial_topics': repeated if penalized else [],
            'note': ('Финансовая тема уже представлена выше. При составлении подборки её повтор имеет меньший приоритет; оценка модели не изменена.'
                     if penalized else 'Приоритет определяется оценкой модели для выбранной роли.'),
        }
        if entry.get('eligible'):
            covered.update(set(entry.get('topics', [])) & FINANCIAL_AXES)
        result.append(entry)
    return result
