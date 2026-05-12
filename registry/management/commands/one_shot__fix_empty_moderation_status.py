from core.management.abstract_command import AbstractCommand
from crawling.models import CrawlingModeration
from fetching.models.oclocher_moderation_models import (
    OClocherOrganizationModeration, OClocherMatchingModeration,
)
from front.models.report_models import ReportModeration
from registry.models.base_moderation_models import ModerationStatus
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
    ReportModeration,
]


class Command(AbstractCommand):
    help = "Fix moderation rows with empty status by setting them to TO_VALIDATE."

    def handle(self, *args, **options):
        self.info('Fixing moderations with empty status...')

        for model_class in ALL_MODERATION_MODELS:
            name = model_class.__name__
            for target, label in [
                (model_class, name),
                (model_class.history.model, f'Historical{name}'),
            ]:
                updated = target.objects.filter(status='').update(
                    status=ModerationStatus.TO_VALIDATE,
                )
                self.info(f'{label}: {updated} rows updated')

        self.success('Done.')
