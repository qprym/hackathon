"""Evaluate factual labels; AI and historical reviews cannot pass independent acceptance."""
import argparse
import json
from pathlib import Path


def evaluate_claims(data):
    facts = [c for c in data['claims'] if not c.get('assumption')]
    current = [c for c in facts if not c.get('outdated', True)]
    historical = [c for c in facts if c.get('outdated', True)]
    def group(items):
        missing = sum(type(c.get('supported')) is not bool or not c.get('reviewer') for c in items)
        complete = bool(items) and not missing and bool(data.get('reviewer')) and bool(data.get('reviewed_at'))
        return {'claims':len(items), 'missing_labels':missing,
                'supported_fraction':sum(c['supported'] for c in items)/len(items) if complete else None}
    kind = data.get('reviewer_kind', 'human')
    independent = kind == 'human' and data.get('independent', True) is True
    result = {'reviewer_kind':kind,'independent':independent,
              'current':group(current),'historical':group(historical),
              'scenarios_excluded_from_factual_metric':len(data['claims'])-len(facts)}
    rate = result['current']['supported_fraction']
    result.update(status='reviewed' if rate is not None else 'historical_only' if historical and result['historical']['supported_fraction'] is not None else 'incomplete',
                  acceptance_eligible=independent and rate is not None,
                  target_met=rate >= .95 if rate is not None and independent else None)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    result = evaluate_claims(json.loads(args.file.read_text(encoding='utf8')))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['status']=='reviewed' else 2)
