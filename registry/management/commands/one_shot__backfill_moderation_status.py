from django.db.models import F

from core.management.abstract_command import AbstractCommand
from crawling.models import CrawlingModeration
from fetching.models.oclocher_moderation_models import (
    OClocherOrganizationModeration, OClocherMatchingModeration,
)
from registry.models.moderation_models import (
    WebsiteModeration, ParishModeration, ChurchModeration,
)
from scheduling.models.parsing_models import ParsingModeration
from scheduling.models.pruning_models import PruningModeration, SentenceModeration
from scheduling.models.scheduling_moderation_models import (
    SchedulingModeration, ValidatedSchedulesModeration,
)

ALL_MODERATION_MODELS = [
    WebsiteModeration,
    ParishModeration,
    ChurchModeration,
    CrawlingModeration,
    SchedulingModeration,
    ValidatedSchedulesModeration,
    ParsingModeration,
    PruningModeration,
    SentenceModeration,
    OClocherOrganizationModeration,
    OClocherMatchingModeration,
]


class Command(AbstractCommand):
    help = "Backfill moderation status from validated_at/marked_as_bug_at."

    def handle(self, *args, **options):
        self.info('Starting backfill of moderation status...')

        for model_class in ALL_MODERATION_MODELS:
            name = model_class.__name__
            for target, label in [
                (model_class, name),
                (model_class.history.model, f'Historical{name}'),
            ]:
                validated = target.objects.filter(
                    validated_at__isnull=False,
                ).update(status='validated')
                bug = target.objects.filter(
                    marked_as_bug_at__isnull=False,
                    validated_at__isnull=True,
                ).update(status='bug')
                comment = target.objects.filter(
                    bug_description__isnull=False,
                ).exclude(
                    bug_description='',
                ).update(comment=F('bug_description'))
                self.info(
                    f'{label}: {validated} validated,'
                    f' {bug} bug, {comment} comments copied'
                )

        self.success('Backfill complete.')
