from django.contrib.auth.models import User

from attaching.models import ImageModeration
from crawling.models import CrawlingModeration
from fetching.models import OClocherOrganizationModeration, OClocherMatchingModeration
from front.models import ApprovalModeration, ConversationModeration, IssueModeration
from registry.models import WebsiteModeration, ChurchModeration, ParishModeration
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
    IssueModeration,
    ApprovalModeration,
    CrawlingModeration,
    SchedulingModeration,
    ValidatedSchedulesModeration,
    OClocherOrganizationModeration,
    OClocherMatchingModeration,
    ConversationModeration,
    ImageModeration,
]


# Groups are created by hand in the Django admin: anyone outside `developer` is a moderator.
DEVELOPER_GROUP_NAME = 'developer'

# A moderator only handles what visitors send us, and only the rows still to validate:
# a bug is always a developer matter.
MODERATOR_RESOURCES = {
    IssueModeration.resource,
    ApprovalModeration.resource,
    ConversationModeration.resource,
    ImageModeration.resource,
}


def is_developer(user: User) -> bool:
    return user.groups.filter(name=DEVELOPER_GROUP_NAME).exists()


def get_moderation_stats(user: User) -> tuple[list[dict], list[dict]]:
    """Return (mine, others): the stats this user is expected to handle, then all the rest.

    Runs one grouped query per moderation model. The two scopes are complementary: a moderator
    owns the to_validate rows of the issue/approval/conversation/image resources, a developer owns
    everything else, every bug included.
    """
    moderator_stats = []
    developer_stats = []

    for moderation_class in MODERATION_CLASSES:
        for stat in moderation_class.get_stats_by_category():
            if stat['bug_count']:
                developer_stats.append(moderation_class.get_category_stat(
                    stat, status=ModerationStatus.BUG, count=stat['bug_count']))
            to_validate_count = stat['total_count'] - stat['bug_count']
            if to_validate_count:
                stats = moderator_stats \
                    if moderation_class.resource in MODERATOR_RESOURCES \
                    else developer_stats
                stats.append(moderation_class.get_category_stat(
                    stat, status=ModerationStatus.TO_VALIDATE, count=to_validate_count))

    if is_developer(user):
        return developer_stats, moderator_stats

    return moderator_stats, developer_stats
