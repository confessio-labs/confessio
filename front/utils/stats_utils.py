import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID

Period = Literal['month', 'week']
PERIODS: tuple[Period, ...] = ('month', 'week')

# Validated categorical order (light surface), see the dataviz palette. Never cycled: past the
# last slot, series fold into OTHER_LABEL.
SERIES_COLORS = [
    '#2a78d6', '#eb6834', '#1baf7a', '#eda100',
    '#e87ba4', '#008300', '#6250d6', '#e34948',
]
OTHER_LABEL = 'Autres'
OTHER_COLOR = '#8a8984'


def parse_period(value: str | None) -> Period:
    return value if value in PERIODS else 'month'


def bucket_start(day: date, period: Period) -> date:
    if period == 'month':
        return day.replace(day=1)
    return day - timedelta(days=day.weekday())


def next_bucket(bucket: date, period: Period) -> date:
    if period == 'month':
        return (bucket.replace(day=28) + timedelta(days=4)).replace(day=1)
    return bucket + timedelta(days=7)


def period_range(first: date, last: date, period: Period) -> list[date]:
    buckets = []
    bucket = bucket_start(first, period)
    while bucket <= last:
        buckets.append(bucket)
        bucket = next_bucket(bucket, period)
    return buckets


def format_bucket(bucket: date, period: Period) -> str:
    return bucket.strftime('%Y-%m') if period == 'month' else bucket.isoformat()


def fold_series(series: dict[str, dict[date, float]]) -> dict[str, dict[date, float]]:
    ranked = sorted(series.items(), key=lambda item: -sum(item[1].values()))
    if len(ranked) <= len(SERIES_COLORS):
        return dict(ranked)

    kept = dict(ranked[:len(SERIES_COLORS) - 1])
    other: dict[date, float] = {}
    for _, values in ranked[len(SERIES_COLORS) - 1:]:
        for bucket, value in values.items():
            other[bucket] = other.get(bucket, 0) + value
    kept[OTHER_LABEL] = other
    return kept


def build_chart(series: dict[str, dict[date, float | None]], period: Period, until: date,
                fill: float | None = 0, chart_type: str = 'bar', stacked: bool = False) -> dict:
    buckets_with_data = [bucket for values in series.values() for bucket in values]
    buckets = period_range(min(buckets_with_data), until, period) if buckets_with_data else []

    datasets = []
    for i, (label, values) in enumerate(series.items()):
        color = OTHER_COLOR if label == OTHER_LABEL else SERIES_COLORS[i % len(SERIES_COLORS)]
        datasets.append({
            'label': label,
            'data': [values.get(bucket, fill) for bucket in buckets],
            'color': color,
        })

    return {
        'type': chart_type,
        'stacked': stacked,
        'labels': [format_bucket(bucket, period) for bucket in buckets],
        'datasets': datasets,
    }


@dataclass(frozen=True)
class HistoryRow:
    uuid: UUID
    at: datetime
    is_creation: bool
    # A creation replayed by a data migration, long after the moderation really arrived.
    is_backfill: bool
    is_deletion: bool
    is_to_validate: bool
    is_validated: bool


@dataclass(frozen=True)
class Episode:
    arrived_at: datetime
    resolved_at: datetime | None


def _by_uuid(rows: list[HistoryRow]) -> list[list[HistoryRow]]:
    """Rows must already be sorted by uuid, then chronologically."""
    groups: list[list[HistoryRow]] = []
    for row in rows:
        if groups and groups[-1][0].uuid == row.uuid:
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def _is_arrival(previous: HistoryRow | None, row: HistoryRow) -> bool:
    if row.is_deletion or not row.is_to_validate:
        return False
    if previous is None:
        # Otherwise the moderation predates its history: we don't know when it arrived. Counting
        # backfills would only keep the ones still pending at migration time and bias cohorts.
        return row.is_creation and not row.is_backfill
    return not previous.is_to_validate


def _is_validation(previous: HistoryRow | None, row: HistoryRow) -> bool:
    if row.is_deletion or not row.is_validated:
        return False
    if previous is None:
        # A moderation created already validated was never validated by anyone, whereas a
        # first change on a moderation that predates its history is a real one.
        return not row.is_creation
    return not previous.is_validated


def transitions(rows: list[HistoryRow]) -> tuple[list[datetime], list[datetime]]:
    """Return (arrival dates, validation dates)."""
    arrivals, validations = [], []
    for group in _by_uuid(rows):
        previous = None
        for row in group:
            if _is_arrival(previous, row):
                arrivals.append(row.at)
            if _is_validation(previous, row):
                validations.append(row.at)
            previous = row
    return arrivals, validations


def episodes(rows: list[HistoryRow]) -> list[Episode]:
    """An episode runs from an arrival to the next validation. One ended by a deletion is
    dropped: the moderation was removed (or converted), not resolved."""
    result = []
    for group in _by_uuid(rows):
        previous = None
        arrived_at = None
        for row in group:
            if arrived_at is not None and row.is_deletion:
                arrived_at = None
            elif arrived_at is not None and _is_validation(previous, row):
                result.append(Episode(arrived_at, row.at))
                arrived_at = None
            elif _is_arrival(previous, row):
                arrived_at = row.at
            previous = row
        if arrived_at is not None:
            result.append(Episode(arrived_at, None))
    return result


def resolution_stats(delays_in_days: list[float | None]) -> tuple[float, float | None]:
    """Return (% resolved, median delay in days). Unresolved items count as infinitely long, so
    the median only exists once at least half of them are resolved."""
    delays = [math.inf if delay is None else delay for delay in delays_in_days]
    resolved_count = sum(1 for delay in delays if not math.isinf(delay))
    median = statistics.median_low(delays)
    return (
        round(100 * resolved_count / len(delays), 1),
        None if math.isinf(median) else round(median, 1),
    )


def cohort_resolution(cohort_episodes: list[Episode], period: Period,
                      to_local_date) -> dict[date, tuple[float, float | None]]:
    cohorts: dict[date, list[float | None]] = {}
    for episode in cohort_episodes:
        cohort = bucket_start(to_local_date(episode.arrived_at), period)
        delay = None
        if episode.resolved_at is not None:
            delay = (episode.resolved_at - episode.arrived_at).total_seconds() / 86400
        cohorts.setdefault(cohort, []).append(delay)
    return {cohort: resolution_stats(delays) for cohort, delays in cohorts.items()}
