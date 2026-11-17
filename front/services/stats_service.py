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
from front.utils.stats_utils import PROCESSING_QUANTILE, HistoryRow, Period, bucket_start, \
    build_chart, cohort_resolution, episodes, fold_series, transitions
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
            is_bug=status == ModerationStatus.BUG,
            user_id=user_id,
        )
        for uuid, history_date, created_at, history_type, status, user_id in
        moderation_class.history.order_by('uuid', 'history_date', 'history_id')
        .values_list('uuid', 'history_date', 'created_at', 'history_type', 'status',
                     'history_user_id')
    ]


def get_moderator_volume_chart(arrivals: list[HistoryRow], validations: list[HistoryRow],
                               bugs: list[HistoryRow], period: Period) -> dict:
    return build_chart({
        'Nouvelles modérations': _count_dates([row.at for row in arrivals], period),
        'Validations': _count_dates([row.at for row in validations], period),
        'Passages en bugs': _count_dates([row.at for row in bugs], period),
    }, period, localdate())


def get_resolution_chart(rows: list[HistoryRow], period: Period) -> dict:
    stats = cohort_resolution(episodes(rows), period, _local_date)
    delay_label = f'Délai {round(100 * PROCESSING_QUANTILE)}e centile (jours)'
    chart = build_chart({
        '% traitées': {cohort: pct for cohort, (pct, _) in stats.items()},
        delay_label: {cohort: delay for cohort, (_, delay) in stats.items()},
    }, period, localdate(), fill=None)
    chart['y_title'] = '% traitées'
    chart['y_max'] = 100
    chart['y2_title'] = delay_label
    chart['datasets'][1].update(type='line', yAxisID='y2')
    return chart


def get_transitions_by_user_chart(transition_rows: list[HistoryRow], period: Period) -> dict:
    dates_by_user_id: dict[int, list[datetime]] = {}
    for row in transition_rows:
        if row.user_id is not None:
            dates_by_user_id.setdefault(row.user_id, []).append(row.at)

    series = _label_by_user({
        user_id: _count_dates(dates, period)
        for user_id, dates in dates_by_user_id.items()
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
    arrivals, validations, bugs = transitions(moderator_rows)
    return {
        'traffic': get_traffic_chart(period),
        'engagement': get_engagement_chart(period),
        'moderator_volume': get_moderator_volume_chart(arrivals, validations, bugs, period),
        'resolution': get_resolution_chart(moderator_rows, period),
        'validations_by_user': get_transitions_by_user_chart(validations, period),
        'bugs_by_user': get_transitions_by_user_chart(bugs, period),
        'messages_by_user': get_messages_by_user_chart(period),
        'validated_schedules_by_user': get_validated_schedules_by_user_chart(period),
    }
