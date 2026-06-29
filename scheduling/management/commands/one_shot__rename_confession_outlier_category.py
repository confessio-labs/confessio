from core.management.abstract_command import AbstractCommand
from scheduling.models.pruning_models import SentenceModeration

OLD_CATEGORY = "confession_outlier"
NEW_CATEGORY = SentenceModeration.Category.V2_OUTLIER


class Command(AbstractCommand):
    help = "One shot: rename SentenceModeration category confession_outlier -> v2_outlier."

    def handle(self, *args, **options):
        n_main = SentenceModeration.objects.filter(
            category=OLD_CATEGORY).update(category=NEW_CATEGORY)
        n_hist = SentenceModeration.history.model.objects.filter(
            category=OLD_CATEGORY).update(category=NEW_CATEGORY)
        self.success(f'Renamed {n_main} SentenceModeration rows '
                     f'and {n_hist} historical rows.')
