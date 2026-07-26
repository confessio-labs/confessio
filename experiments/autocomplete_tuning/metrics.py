"""Ranking metrics + table rendering for the autocomplete tuning harness."""
from dataclasses import dataclass


@dataclass
class HitOutcome:
    item_type: str
    rank: int | None      # 1-based rank of the target URL in the replayed list, None if absent
    in_train: bool


def _row(outcomes: list[HitOutcome]) -> dict:
    n = len(outcomes)
    if n == 0:
        return {'n': 0, 'top1': 0.0, 'top3': 0.0, 'mrr': 0.0, 'recall15': 0.0}
    return {
        'n': n,
        'top1': sum(1 for o in outcomes if o.rank == 1) / n,
        'top3': sum(1 for o in outcomes if o.rank is not None and o.rank <= 3) / n,
        'mrr': sum(1.0 / o.rank for o in outcomes if o.rank is not None) / n,
        'recall15': sum(1 for o in outcomes if o.rank is not None) / n,
    }


def summarize(outcomes: list[HitOutcome]) -> dict[str, dict]:
    rows = {'overall': _row(outcomes)}
    for item_type in ('municipality', 'parish', 'church'):
        rows[item_type] = _row([o for o in outcomes if o.item_type == item_type])
    return rows


def render(runs: dict[str, dict[str, dict]], skips: dict[str, int] | None = None) -> str:
    """runs: {run_label: summarize(...) result}. Renders one block per run + deltas vs first."""
    lines = []
    labels = list(runs)
    base = runs[labels[0]]
    header = f"{'':22s}{'n':>6s}  {'top-1':>7s} {'top-3':>7s} {'MRR':>7s} {'rec@15':>7s}"
    for label in labels:
        lines.append(f"== {label} ==")
        lines.append(header)
        for name, r in runs[label].items():
            deltas = ''
            if label != labels[0] and base[name]['n']:
                deltas = (f"   (Δ top-1 {r['top1'] - base[name]['top1']:+.3f},"
                          f" MRR {r['mrr'] - base[name]['mrr']:+.3f})")
            lines.append(f"{name:22s}{r['n']:>6d}  {r['top1']:>7.3f} {r['top3']:>7.3f}"
                         f" {r['mrr']:>7.3f} {r['recall15']:>7.3f}{deltas}")
        lines.append('')
    if skips:
        total = sum(skips.values())
        detail = ', '.join(f'{k}: {v}' for k, v in sorted(skips.items()))
        lines.append(f'skipped hits: {total} ({detail})')
    return '\n'.join(lines)
