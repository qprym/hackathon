"""Operational measurements, separated from independent quality labels."""
from collections import Counter
from math import ceil


def mode_metrics(runs, usage):
    paid_runs = {u.run_id for u in usage if u.run_id}
    groups = {mode: [] for mode in ('live', 'demo', 'unknown')}
    for run in runs:
        mode = (run.result or {}).get('mode')
        if mode not in ('live', 'demo'):
            mode = 'live' if run.id in paid_runs else 'unknown'
        groups[mode].append(run)
    result = {}
    for mode, members in groups.items():
        durations = sorted((r.finished_at-r.created_at).total_seconds() for r in members
                           if r.status == 'completed' and r.finished_at and r.finished_at >= r.created_at)
        percentile = lambda q: round(durations[max(ceil(len(durations)*q)-1, 0)], 2) if durations else None
        result[mode] = {'total': len(members), 'statuses': dict(Counter(r.status for r in members)),
            'checked': sum((r.result or {}).get('verification') == 'checked' for r in members),
            'insufficient': sum((r.result or {}).get('verification') == 'insufficient' for r in members),
            'latency_samples': len(durations),
            'latency_avg_seconds': round(sum(durations)/len(durations), 2) if durations else None,
            'latency_p50_seconds': percentile(.5), 'latency_p95_seconds': percentile(.95)}
    result['live']['provider_calls'] = len(usage)
    result['live']['provider_cost_rub'] = round(sum(u.cost_rub for u in usage), 5)
    return result
