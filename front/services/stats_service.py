from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import connection
from django.db.models import Count, DateField, QuerySet
from django.db.models.functions import Trunc
from django.utils.timezone import localdate, localtime
from request.models import Request

from attaching.models import FileNote, FileNoteComment, TextNote, TextNoteComment
from front.models import Approval, ApprovalComment, Issue, IssueComment, Message
from front.services.moderation_stats_service import MODERATION_CLASSES, MODERATOR_RESOURCES
from front.utils.stats_utils import HistoryRow, Period, bucket_start, build_chart, \
    cohort_resolution, episodes, fold_series, transitions
from registry.models.base_moderation_models import ModerationStatus
from scheduling.models import ValidatedSchedules

MODERATOR_CLASSES = [cls for cls in MODERATION_CLASSES if cls.resource in MODERATOR_RESOURCES]
# A live creation is logged within milliseconds of created_at; a backfill keeps the original one.
BACKFILL_MIN_DELAY = timedelta(hours=1)
COMMENT_CLASSES = [IssueComment, ApprovalComment, FileNoteComment, TextNoteComment]


def _local_date(dt: datetime) -> date:
    return localtime(dt).date()


def _count_by_bucket(queryset: QuerySet, date_field: str, period: Period) -> dict[date, int]:
    # order_by() drops the model's default ordering, which would otherwise split the groups.
    return dict(
        queryset.order_by()
        .annotate(bucket=Trunc(date_field, period, output_field=DateField()))
        .values('bucket')
        .annotate(count=Count('pk'))
        .values_list('bucket', 'count')
    )


def _count_by_user_and_bucket(queryset: QuerySet, user_field: str, date_field: str,
                              period: Period) -> dict[int, dict[date, int]]:
    rows = (
        queryset.order_by()
        .filter(**{f'{user_field}__isnull': False})
        .annotate(bucket=Trunc(date_field, period, output_field=DateField()))
        .values_list(user_field, 'bucket')
        .annotate(count=Count('pk'))
    )
    series: dict[int, dict[date, int]] = {}
    for user_id, bucket, count in rows:
        series.setdefault(user_id, {})
        series[user_id][bucket] = series[user_id].get(bucket, 0) + count
    return series


def _count_dates(dates: list[datetime], period: Period) -> dict[date, int]:
    counts: dict[date, int] = {}
    for dt in dates:
        bucket = bucket_start(_local_date(dt), period)
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def _sum_counts(*all_counts: dict[date, int]) -> dict[date, int]:
    total: dict[date, int] = {}
    for counts in all_counts:
        for bucket, count in counts.items():
            total[bucket] = total.get(bucket, 0) + count
    return total


def _merge_series(*all_series: dict[int, dict[date, int]]) -> dict[int, dict[date, int]]:
    merged: dict[int, dict[date, int]] = {}
    for series in all_series:
        for key, counts in series.items():
            merged[key] = _sum_counts(merged.get(key, {}), counts)
    return merged


def _label_by_user(series_by_user_id: dict[int, dict[date, int]]) -> dict[str, dict[date, int]]:
    users = User.objects.in_bulk(list(series_by_user_id))
    labeled: dict[str, dict[date, int]] = {}
    for user_id, counts in series_by_user_id.items():
        user = users[user_id]
        label = user.first_name or user.username
        labeled[label] = _sum_counts(labeled.get(label, {}), counts)
    return labeled


###########
# Traffic #
###########

def get_traffic_chart(period: Period) -> dict:
    # A visitor is approximated by a (user agent, hour) pair: we don't log IPs.
    query = f"""
        SELECT (date_trunc(%s, time_hour AT TIME ZONE %s))::date, count(*)
        FROM (
            SELECT date_trunc('hour', time) AS time_hour, user_agent
            FROM {Request._meta.db_table}
            WHERE referer LIKE 'https://confessio.fr%%'
            GROUP BY 1, 2
        ) sub
        GROUP BY 1
    """
    with connection.cursor() as cursor:
        cursor.execute(query, [period, settings.TIME_ZONE])
        counts = dict(cursor.fetchall())

    return build_chart({'Visiteurs uniques': counts}, period, localdate())


def get_engagement_chart(period: Period) -> dict:
    series = {
        'Issues': _count_by_bucket(Issue.objects.filter(user__isnull=True), 'created_at', period),
        'Approvals': _count_by_bucket(Approval.objects.filter(user__isnull=True), 'created_at',
                                      period),
        'Notes fichier': _count_by_bucket(FileNote.objects.filter(user__isnull=True),
                                          'created_at', period),
        'Notes texte': _count_by_bucket(TextNote.objects.filter(user__isnull=True),
                                        'created_at', period),
        'Commentaires': _sum_counts(*(
            _count_by_bucket(cls.objects.filter(user__isnull=True), 'created_at', period)
            for cls in COMMENT_CLASSES
        )),
        'Messages reçus': _count_by_bucket(
            Message.objects.filter(direction=Message.Direction.INBOUND), 'created_at', period),
    }
    return build_chart(series, period, localdate(), stacked=True)


##############
# Moderation #
##############

def _history_rows(moderation_class) -> list[HistoryRow]:
    return [
        HistoryRow(
            uuid=uuid,
            at=history_date,
            is_creation=history_type == '+',
            is_backfill=history_type == '+' and history_date - created_at > BACKFILL_MIN_DELAY,
            is_deletion=history_type == '-',
            is_to_validate=status == ModerationStatus.TO_VALIDATE,
            is_validated=status == ModerationStatus.VALIDATED,
        )
        for uuid, history_date, created_at, history_type, status in
        moderation_class.history.order_by('uuid', 'history_date', 'history_id')
        .values_list('uuid', 'history_date', 'created_at', 'history_type', 'status')
    ]


def _user_validations(moderation_class) -> list[tuple[datetime, int]]:
    """Return (date, user id) of each validation made by someone.

    A deletion counts too: some categories are deleted on validation, and the history can't tell
    that apart from the delete button, which is a moderation action as well.
    """
    table = moderation_class.history.model._meta.db_table
    # Done in SQL: the scheduling and crawling histories are too big to load in Python. The window
    # only runs on moderations someone touched.
    query = f"""
        SELECT history_date, history_user_id
        FROM (
            SELECT history_date, history_user_id, history_type, status,
                   lag(status) OVER (PARTITION BY uuid ORDER BY history_date, history_id)
                       AS previous_status
            FROM {table}
            WHERE uuid IN (SELECT uuid FROM {table} WHERE history_user_id IS NOT NULL)
        ) h
        WHERE history_user_id IS NOT NULL
          AND (
              (history_type = '~' AND status = %(validated)s
               AND previous_status IS DISTINCT FROM %(validated)s)
              OR (history_type = '-' AND status <> %(validated)s)
          )
    """
    with connection.cursor() as cursor:
        cursor.execute(query, {'validated': ModerationStatus.VALIDATED.value})
        return cursor.fetchall()


def get_moderator_volume_chart(rows: list[HistoryRow], period: Period) -> dict:
    arrivals, validations = transitions(rows)
    return build_chart({
        'Modérations à traiter': _count_dates(arrivals, period),
        'Validations': _count_dates(validations, period),
    }, period, localdate())


def get_resolution_chart(rows: list[HistoryRow], period: Period) -> dict:
    stats = cohort_resolution(episodes(rows), period, _local_date)
    chart = build_chart({
        '% résolues': {cohort: pct for cohort, (pct, _) in stats.items()},
        'Délai médian (jours)': {cohort: median for cohort, (_, median) in stats.items()},
    }, period, localdate(), fill=None)
    chart['y_title'] = '% résolues'
    chart['y_max'] = 100
    chart['y2_title'] = 'Délai médian (jours)'
    chart['datasets'][1].update(type='line', yAxisID='y2')
    return chart


def get_validations_by_user_chart(period: Period) -> dict:
    validations_by_user_id: dict[int, list[datetime]] = {}
    for moderation_class in MODERATION_CLASSES:
        for history_date, user_id in _user_validations(moderation_class):
            validations_by_user_id.setdefault(user_id, []).append(history_date)

    series = _label_by_user({
        user_id: _count_dates(dates, period)
        for user_id, dates in validations_by_user_id.items()
    })
    return build_chart(fold_series(series), period, localdate(), stacked=True)


def get_messages_by_user_chart(period: Period) -> dict:
    series = _merge_series(
        _count_by_user_and_bucket(
            Message.objects.filter(direction=Message.Direction.OUTBOUND), 'author', 'created_at',
            period),
        *(_count_by_user_and_bucket(cls.objects.all(), 'user', 'created_at', period)
          for cls in COMMENT_CLASSES),
    )
    return build_chart(fold_series(_label_by_user(series)), period, localdate(), stacked=True)


def get_validated_schedules_by_user_chart(period: Period) -> dict:
    series = _count_by_user_and_bucket(ValidatedSchedules.objects.all(), 'validated_by',
                                       'validated_at', period)
    return build_chart(fold_series(_label_by_user(series)), period, localdate(), stacked=True)


def get_stats_charts(period: Period) -> dict[str, dict]:
    moderator_rows = [row for cls in MODERATOR_CLASSES for row in _history_rows(cls)]
    return {
        'traffic': get_traffic_chart(period),
        'engagement': get_engagement_chart(period),
        'moderator_volume': get_moderator_volume_chart(moderator_rows, period),
        'resolution': get_resolution_chart(moderator_rows, period),
        'validations_by_user': get_validations_by_user_chart(period),
        'messages_by_user': get_messages_by_user_chart(period),
        'validated_schedules_by_user': get_validated_schedules_by_user_chart(period),
    }
