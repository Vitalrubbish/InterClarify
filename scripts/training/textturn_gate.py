"""Evaluate low development floors and rank only qualified controller candidates first."""
from __future__ import annotations

import math


POSITIVES = ('smooth', 'declarative', 'interruption')
NEGATIVES = ('pause_false_start', 'backchannel_false_stop')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _metric(value):
    if not isinstance(value, dict):
        return False
    numerator, denominator, rate = (value.get(k) for k in ('numerator', 'denominator', 'rate'))
    return (type(numerator) is int and type(denominator) is int and 0 <= numerator <= denominator and
            denominator > 0 and _number(rate) and
            math.isclose(rate, numerator / denominator, rel_tol=1e-9, abs_tol=1e-12))


def development_gate(baseline, candidate, config):
    """Return auditable independent conditions; unknown or incomplete metrics fail closed."""
    tolerance = config['false_action_regression_tolerance']
    if not _number(tolerance) or tolerance < 0:
        raise ValueError('False-action tolerance must be finite and nonnegative')
    conditions, details = {}, {}
    scores = [v.get('opportunity_score') for v in (baseline, candidate)]
    conditions['score_improved'] = all(_number(s) for s in scores) and scores[1] > scores[0]
    for name in NEGATIVES:
        before, after = baseline.get(name), candidate.get(name)
        conditions[name + '_regression'] = bool(_metric(before) and _metric(after) and
                                                after['rate'] <= before['rate'] + tolerance)
    policy = config.get('development_gate')
    if policy is not None:
        floors = policy.get('minimum_success_rates', {})
        if set(floors) != set(POSITIVES) or any(not _number(v) or not 0 < v <= 1 for v in floors.values()):
            raise ValueError('Provide finite positive floors for all three positive development metrics')
        for name in POSITIVES + NEGATIVES:
            before, after = baseline.get(name), candidate.get(name)
            complete = bool(_metric(before) and _metric(after) and after.get('unknown') == 0 and
                            after.get('planned') == after['denominator'] == before['denominator'] and
                            before.get('planned') == before['denominator'] and before.get('unknown') == 0)
            conditions[name + '_complete'] = complete
            if name in floors:
                required = max(1, math.ceil(floors[name] * after['denominator'] - 1e-12)) if complete else None
                conditions[name + '_floor'] = complete and after['numerator'] >= required
                details[name] = {'minimum_rate': floors[name], 'required_successes': required,
                                 'observed_successes': after.get('numerator') if isinstance(after, dict) else None,
                                 'denominator': after.get('denominator') if isinstance(after, dict) else None}
        before, after = baseline.get('runtime'), candidate.get('runtime')
        conditions['runtime_complete'] = bool(_metric(before) and _metric(after) and
            after['numerator'] == after['denominator'] == before['denominator'] == before['numerator'])
    return {'passed': all(conditions.values()), 'conditions': conditions,
            'reasons': [name for name, passed in conditions.items() if not passed],
            'positive_floors': details, 'false_action_regression_tolerance': tolerance}


def selection_key(record, baseline, config):
    """Prefer qualified full candidates, then score; retain failed epochs for diagnostics."""
    score = record['dev']['opportunity_score']
    score = score if _number(score) else -math.inf
    if config.get('development_gate') is None:
        return (score,)
    eligible = development_gate(baseline, record['dev'], config)['passed']
    return eligible, eligible and record['stage'] == 'full', score


def candidate_gate(baseline, selection, config, stage_completed):
    """Recheck the selected weights rather than reusing the pilot continuation flag."""
    report = development_gate(baseline, selection['dev'], config)
    if config.get('development_gate') is not None:
        report['conditions']['selected_full_candidate'] = stage_completed == selection['stage'] == 'full'
        report['passed'] = all(report['conditions'].values())
        report['reasons'] = [name for name, passed in report['conditions'].items() if not passed]
    return report
