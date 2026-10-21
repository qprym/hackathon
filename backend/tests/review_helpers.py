"""Protocol fixtures, never a substitute for semantic quality evaluation."""
def accepted_review(packet):
    sources = {e['id']: e for e in packet['evidence']}
    return {'checks': [
        {'item_id': item_id, 'verdict': 'supported', 'category': 'none',
         'text_span': item['text'], 'reason': 'Контрольный ответ проверяющего для теста протокола.',
         'quotes': [{'evidence_id': ref, 'quote': sources[ref]['excerpt'][:200]}
                    for ref in item.get('evidence_ids', [])],
         'feature_keys': list(packet['company_grounds'][item_id])}
        for item_id, item in packet['items'].items()]}


def rejected_review(packet, item_id='impact.0'):
    review = accepted_review(packet)
    check = next(c for c in review['checks'] if c['item_id'] == item_id)
    check.update(verdict='uncertain', category='grounds', reason='Нужна проверка фактического условия сценария.',
                 correction='Уточнить условие рефинансирования.')
    return review


def unchanged_patch(payload):
    draft = payload['draft_to_correct']
    edits = []
    for item_id in payload['allowed_edits']:
        if item_id == 'headline':
            value = draft['headline']
        else:
            section, i = item_id.split('.')
            value = draft[section][int(i)]
        edits.append({'item_id': item_id, 'replacement': value})
    return {'edits': edits}
