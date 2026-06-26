from core.management.abstract_command import AbstractCommand
from scheduling.models.pruning_models import Sentence


class Command(AbstractCommand):
    help = "One shot command to fill history temporal."

    def handle(self, *args, **options):
        counter = 0
        for sentence in Sentence.objects.all():
            assert sentence.ml_temporal is not None
            Sentence.history.model.objects.filter(
                uuid=sentence.uuid,
                ml_temporal__isnull=True
            ).update(ml_temporal=sentence.ml_temporal)

            counter += 1
            if counter % 100 == 0:
                self.stdout.write(f'Processed {counter} sentences...')

        self.success(f'Successfully fill {counter} history temporal.')
