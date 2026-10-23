"""Read-only saved-response audit. No settings, database or LLM gateway imports."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from .schemas import Insight
from .validation import validate_insight
from .cashflow import VALIDATION_VERSION, financial_findings
from .review import assess_review, review_items


def replay(directory, annotations=()):
    labels = {(a['run_id'], a['attempt'], a['issue_index']): a for a in annotations}
    records, counts = [], Counter()
    for path in sorted(Path(directory).glob('live-*.json')):
        run = json.loads(path.read_text(encoding='utf-8'))['run']
        result = run.get('result') or {}
        sources = {e['id']: e for e in result.get('evidence', [])}
        context = {'features': result.get('context_features', {})}
        steps = run.get('trace', [])
        attempts = {}
        for step in steps:
            detail = step['details']
            if step['step'] in ('Поиск аналитики', 'Дополнительный поиск'):
                attempts.setdefault(detail['attempt'], {})['source_ids'] = detail['source_ids']
            elif step['step'] == 'Черновик анализа':
                attempts.setdefault(detail['attempt'], {})['draft'] = detail['draft']
            elif step['step'] == 'Проверка оснований':
                attempts.setdefault(detail['attempt'], {})['review'] = detail
            elif step['step'] == 'Пакет проверки':
                attempts.setdefault(detail['attempt'], {})['review_packet'] = detail['payload']
            elif step['step'] == 'Ответ проверяющего':
                attempts.setdefault(detail['attempt'], {})['review_response'] = detail['response']
        for attempt, saved in attempts.items():
            if 'draft' not in saved:
                continue
            counts['drafts'] += 1
            financial = financial_findings(review_items(Insight.model_validate(saved['draft'])))
            if financial:
                counts['cashflow_flagged_drafts'] += 1
            reviewed = None
            if 'review_packet' in saved and 'review_response' in saved:
                current_issues, targets, _ = assess_review(saved['review_response'], saved['review_packet'])
                reviewed = {'issues': current_issues, 'correction_targets': targets,
                            'snapshot': 'exact_saved_review_packet_and_response'}
                counts['saved_reviews_replayed'] += 1
            evidence_ids = saved.get('source_ids', [])
            available = bool(evidence_ids and context['features']) and all(ref in sources for ref in evidence_ids)
            # Old runs did not save request packets. Never borrow evidence/context from another run.
            local_issues = validate_insight(Insight.model_validate(saved['draft']),
                [sources[ref] for ref in evidence_ids], context) if available else None
            issues = []
            if 'review' in saved:
                counts['check_steps'] += 1
            for i, message in enumerate(saved.get('review', {}).get('issues', [])):
                label = labels.get((run['id'], attempt, i))
                if label and hashlib.sha256(message.encode()).hexdigest() != label['issue_sha256']:
                    raise ValueError(f'Annotation does not match saved review: {run["id"]}/{attempt}/{i}')
                classification = label['classification'] if label else 'unclassified'
                counts[classification] += 1
                issues.append({'original': message, 'classification': classification,
                               'reason': label['reason'] if label else None})
            records.append({'run_id': run['id'], 'attempt': attempt, 'saved_status': run['status'],
                'snapshot': 'reconstructed_from_same_run_result' if available else 'missing',
                'local_issues_now': local_issues, 'original_issues': issues,
                'cashflow_issues_now': financial, 'saved_review_replay': reviewed,
                'semantic_status': 'not_rechecked', 'published': False})
    return {'paid_calls': 0, 'validation_version': VALIDATION_VERSION,
            'method': 'local validation, saved review protocol replay and curated annotations; no new model verdict',
            'counts': dict(counts), 'records': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--annotations', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve().is_relative_to(args.input_dir.resolve()) and args.output.name.startswith('live-'):
        parser.error('Choose a new report filename, never an existing snapshot')
    annotations = json.loads(args.annotations.read_text(encoding='utf-8')) if args.annotations else []
    report = replay(args.input_dir, annotations)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'paid_calls': 0, 'counts': report['counts']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
