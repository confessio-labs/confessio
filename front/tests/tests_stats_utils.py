"""Pure unit tests for the stats helpers. No Django / DB needed."""
import unittest
from datetime import date, datetime, timedelta
from uuid import uuid4

from front.utils.stats_utils import OTHER_LABEL, SERIES_COLORS, Episode, HistoryRow, \
    bucket_start, build_chart, cohort_resolution, episodes, fold_series, period_range, \
    resolution_stats, transitions

T0 = datetime(2026, 10, 12, 9, 0)


def row(uuid, hours, status, history_type='~', is_backfill=False):
    return HistoryRow(
        uuid=uuid,
        at=T0 + timedelta(hours=hours),
        is_creation=history_type == '+',
        is_backfill=is_backfill,
        is_deletion=history_type == '-',
        is_to_validate=status == 'to_validate',
        is_validated=status == 'validated',
    )


class BucketTests(unittest.TestCase):
    def test_bucket_start(self):
        self.assertEqual(bucket_start(date(2026, 11, 17), 'month'), date(2026, 11, 1))
        self.assertEqual(bucket_start(date(2026, 11, 17), 'week'), date(2026, 11, 16))
        self.assertEqual(bucket_start(date(2026, 11, 16), 'week'), date(2026, 11, 16))

    def test_period_range_crosses_year(self):
        self.assertEqual(period_range(date(2026, 11, 20), date(2027, 1, 3), 'month'),
                         [date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1)])
        self.assertEqual(period_range(date(2026, 11, 18), date(2026, 11, 30), 'week'),
                         [date(2026, 11, 16), date(2026, 11, 23), date(2026, 11, 30)])

    def test_build_chart_fills_gaps(self):
        chart = build_chart({'a': {date(2026, 9, 1): 3}, 'b': {date(2026, 11, 1): 1}},
                            'month', date(2026, 11, 17))
        self.assertEqual(chart['labels'], ['2026-09', '2026-10', '2026-11'])
        self.assertEqual([d['data'] for d in chart['datasets']], [[3, 0, 0], [0, 0, 1]])

    def test_build_chart_without_data(self):
        self.assertEqual(build_chart({'a': {}}, 'week', date(2026, 11, 17))['labels'], [])

    def test_fold_series_keeps_biggest(self):
        series = {f'user{i}': {date(2026, 11, 1): i} for i in range(len(SERIES_COLORS) + 2)}
        folded = fold_series(series)
        self.assertEqual(len(folded), len(SERIES_COLORS))
        self.assertEqual(list(folded)[0], f'user{len(SERIES_COLORS) + 1}')
        self.assertEqual(folded[OTHER_LABEL], {date(2026, 11, 1): 0 + 1 + 2})


class TransitionTests(unittest.TestCase):
    def test_reopen_counts_two_arrivals(self):
        uuid = uuid4()
        rows = [
            row(uuid, 0, 'to_validate', '+'),
            row(uuid, 1, 'to_validate'),
            row(uuid, 2, 'validated'),
            row(uuid, 3, 'validated'),
            row(uuid, 4, 'to_validate'),
            row(uuid, 5, 'validated'),
        ]
        arrivals, validations = transitions(rows)
        self.assertEqual(arrivals, [rows[0].at, rows[4].at])
        self.assertEqual(validations, [rows[2].at, rows[5].at])

    def test_moderation_older_than_history(self):
        uuid = uuid4()
        rows = [row(uuid, 0, 'to_validate'), row(uuid, 1, 'validated')]
        arrivals, validations = transitions(rows)
        self.assertEqual(arrivals, [])
        self.assertEqual(validations, [rows[1].at])

    def test_backfilled_moderation(self):
        pending, done = uuid4(), uuid4()
        rows = [
            row(pending, 0, 'to_validate', '+', is_backfill=True),
            row(pending, 1, 'validated'),
            row(done, 0, 'validated', '+', is_backfill=True),
        ]
        self.assertEqual(transitions(rows), ([], [rows[1].at]))
        self.assertEqual(episodes(rows), [])

    def test_created_validated_is_not_a_validation(self):
        rows = [row(uuid4(), 0, 'validated', '+')]
        self.assertEqual(transitions(rows), ([], []))

    def test_deletion_is_not_a_validation(self):
        uuid = uuid4()
        rows = [row(uuid, 0, 'to_validate', '+'), row(uuid, 1, 'to_validate', '-')]
        self.assertEqual(transitions(rows), ([rows[0].at], []))


class EpisodeTests(unittest.TestCase):
    def test_episodes(self):
        resolved, deleted, pending = uuid4(), uuid4(), uuid4()
        rows = [
            row(resolved, 0, 'to_validate', '+'),
            row(resolved, 2, 'bug'),
            row(resolved, 5, 'validated'),
            row(deleted, 0, 'to_validate', '+'),
            row(deleted, 1, 'to_validate', '-'),
            row(pending, 3, 'to_validate', '+'),
        ]
        rows.sort(key=lambda r: (r.uuid, r.at))
        self.assertCountEqual(episodes(rows), [
            Episode(T0, T0 + timedelta(hours=5)),
            Episode(T0 + timedelta(hours=3), None),
        ])


class ResolutionTests(unittest.TestCase):
    def test_all_resolved(self):
        self.assertEqual(resolution_stats([1.0, 3.0, 2.0]), (100.0, 2.0))

    def test_exactly_half_resolved(self):
        self.assertEqual(resolution_stats([1.0, None, 3.0, None]), (50.0, 3.0))

    def test_less_than_half_resolved(self):
        self.assertEqual(resolution_stats([1.0, None, None]), (33.3, None))

    def test_cohort_resolution(self):
        november = datetime(2026, 11, 3)
        cohorts = cohort_resolution([
            Episode(november, november + timedelta(days=2)),
            Episode(november, None),
            Episode(datetime(2026, 10, 30), datetime(2026, 11, 2)),
        ], 'month', lambda dt: dt.date())
        self.assertEqual(cohorts, {
            date(2026, 11, 1): (50.0, 2.0),
            date(2026, 10, 1): (100.0, 3.0),
        })


if __name__ == '__main__':
    unittest.main()
