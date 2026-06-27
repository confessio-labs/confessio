from collections import defaultdict

from crawling.models import CrawlingModeration
from fetching.models import OClocherOrganizationModeration, OClocherMatchingModeration
from front.models import ReportModeration
from registry.models import Diocese, WebsiteModeration, ChurchModeration, ParishModeration
from registry.models.base_moderation_models import ModerationStatus
from scheduling.models import ParsingModeration, SchedulingModeration, \
    ValidatedSchedulesModeration
from scheduling.models.pruning_models import PruningModeration, SentenceModeration

MODERATION_CLASSES = [
    WebsiteModeration,
    ParishModeration,
    ChurchModeration,
    PruningModeration,
    SentenceModeration,
    ParsingModeration,
    ReportModeration,
    CrawlingModeration,
    SchedulingModeration,
    ValidatedSchedulesModeration,
    OClocherOrganizationModeration,
    OClocherMatchingModeration,
]


def get_moderation_stats_by_diocese() -> list[tuple[Diocese | None, list[dict]]]:
    """Return [(diocese | None, [stat, ...]), ...] for every diocese with pending moderations.

    Runs one grouped query per moderation model (instead of one per diocese per model), then
    buckets the rows by diocese in Python. The None bucket ("Autre") comes first, followed by
    dioceses sorted by name. Dioceses without any pending moderation are omitted.
    """
    dioceses_by_pk = {diocese.pk: diocese for diocese in Diocese.objects.all()}
    stats_by_diocese_pk = defaultdict(list)

    for moderation_class in MODERATION_CLASSES:
        for stat in moderation_class.get_stats_by_diocese_and_category():
            diocese = dioceses_by_pk.get(stat['diocese'])
            if stat['bug_count']:
                stats_by_diocese_pk[stat['diocese']].append(
                    moderation_class.get_category_stat(
                        stat, status=ModerationStatus.BUG,
                        diocese=diocese, count=stat['bug_count']))
            to_validate_count = stat['total_count'] - stat['bug_count']
            if to_validate_count:
                stats_by_diocese_pk[stat['diocese']].append(
                    moderation_class.get_category_stat(
                        stat, status=ModerationStatus.TO_VALIDATE,
                        diocese=diocese, count=to_validate_count))

    dioceses_with_stats = []
    if None in stats_by_diocese_pk:
        dioceses_with_stats.append((None, stats_by_diocese_pk[None]))
    for diocese in sorted(dioceses_by_pk.values(), key=lambda d: d.name):
        if diocese.pk in stats_by_diocese_pk:
            dioceses_with_stats.append((diocese, stats_by_diocese_pk[diocese.pk]))

    return dioceses_with_stats
