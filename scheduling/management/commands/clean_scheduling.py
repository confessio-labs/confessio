from datetime import timedelta

from django.db.models import Q, Subquery
from django.utils import timezone

from core.management.abstract_cleaning_command import AbstractCleaningCommand
from registry.models.base_moderation_models import ModerationStatus
from scheduling.models import Log as SchedulingLog
from scheduling.models import ParsingModeration, Parsing
from scheduling.models import PruningParsing, ScrapingPruning, ImagePruning
from scheduling.models.pruning_models import Pruning, Sentence, Classifier
from scheduling.services.scheduling.scheduling_service import get_websites_of_parsing


class Command(AbstractCleaningCommand):
    help = "Clean scheduling-related data from the database"

    def handle(self, *args, **options):
        self.info('Starting cleaning old parsings')
        old_parsings = Parsing.objects.filter(
            ~Q(uuid__in=Subquery(Parsing.history.filter(
                history_id__in=Subquery(
                    PruningParsing.objects.values(
                        'parsing_history_id').distinct()
                ),
            ).values('uuid').distinct())),
            human_json__isnull=True,
            updated_at__lt=timezone.now() - timedelta(days=30)
        ).all()
        counter = self.delete_objects(old_parsings)
        self.success(f'Successfully cleaned {counter} old parsings')

        self.clean_history(Parsing, Parsing.history.model)

        self.info('Starting cleaning parsing moderations')
        delete_count = self.clean_parsing_moderations()
        self.success(f'Successfully cleaning {delete_count} parsing moderations')

        self.clean_history(ParsingModeration, ParsingModeration.history.model)

        # Prunings
        self.info('Starting removing orphan prunings')
        orphan_prunings = Pruning.objects.filter(scrapings__isnull=True,
                                                 human_indices__isnull=True,
                                                 images__isnull=True).all()
        counter = self.delete_objects(orphan_prunings)
        self.success(f'Done removing {counter} orphan prunings')

        self.clean_pruning_history()

        # Sentences
        self.info('Starting removing orphan sentences')
        orphan_sentences = Sentence.objects.filter(
            prunings__isnull=True,
            source__exact='ml',
            human_temporal__isnull=True,
            human_confession__isnull=True,
        ).all()
        counter = self.delete_objects(orphan_sentences)
        self.success(f'Done removing {counter} orphan sentences')

        self.clean_history(Sentence, Sentence.history.model)

        # Every reclassification rewrites each sentence's embedding and classifier pointers,
        # storing a full copy of both vectors (~7 KB) in a new history item. Only
        # human-curated changes are worth keeping.
        self.delete_irrelevant_history(Sentence, {
            'updated_at',
            'encoder', 'encoder_embedding',  # v2 embedding
            'transformer_name', 'embedding',  # v1 embedding
            'action', 'classifier',
            'ml_temporal', 'temporal_classifier',
            'ml_confession', 'confession_new_classifier',
        })

        # Classifiers
        self.info('Starting removing draft classifiers, older than 3 days')
        draft_classifiers = Classifier.objects.filter(
            status__exact='draft',
            created_at__lt=timezone.now() - timedelta(days=3)).all()
        counter = self.delete_objects(draft_classifiers)
        self.success(f'Done removing {counter} draft classifiers')

        self.clean_history(Classifier, Classifier.history.model)

        # Logs
        self.info('Starting removing old scheduling logs')
        old_logs = SchedulingLog.objects.filter(
            created_at__lt=timezone.now() - timedelta(days=3)).all()
        counter = self.delete_objects(old_logs)
        self.success(f'Done removing {counter} old scheduling logs')

    def clean_pruning_history(self):
        self.info('Starting cleaning Pruning history items')
        history_model = Pruning.history.model
        query = history_model.objects.filter(
            ~Q(uuid__in=Pruning.objects.values_list('uuid', flat=True)),
        ).exclude(
            Q(history_id__in=ScrapingPruning.objects.values('pruning_history_id'))
            | Q(history_id__in=ImagePruning.objects.values('pruning_history_id'))
            | Q(history_id__in=PruningParsing.objects.values('pruning_history_id'))
        )
        counter = query.count()
        query.delete()
        self.success(f'Done removing {counter} orphan Pruning history items')

    @staticmethod
    def clean_parsing_moderations() -> int:
        counter = 0
        for parsing_moderation in ParsingModeration.objects.exclude(
                status=ModerationStatus.VALIDATED).all():
            if not get_websites_of_parsing(parsing_moderation.parsing):
                parsing_moderation.delete()
                counter += 1

        return counter
