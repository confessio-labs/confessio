from core.management.abstract_command import AbstractCommand
from core.utils.heartbeat_utils import ping_heartbeat
from scheduling.models.pruning_models import Classifier, Sentence
from scheduling.services.pruning.classify_sentence_service import classify_line, get_classifier
from scheduling.services.pruning.train_classifier_service import train_classifier, \
    build_sentence_dataset, \
    extract_label
from scheduling.utils.stat_utils import is_significantly_different


class Command(AbstractCommand):
    help = "Launch the training of machine learning model to guess label of Sentence, given target"

    def add_arguments(self, parser):
        parser.add_argument('-t', '--target', type=Classifier.Target,
                            choices=list(Classifier.Target), help='Target of the classifier')

        parser.add_argument('-l', '--test-on-line', help='test latest classifier on given line')
        parser.add_argument('-a', '--automatic', action='store_true',
                            help='automatic training triggered in nightly job')

    def handle(self, *args, **options):
        target = options['target']
        if target:
            targets = [target]
        else:
            targets = [t for t in Classifier.Target if t != Classifier.Target.ACTION]

        if options['test_on_line']:
            for target in targets:
                self.info(f'Testing classifier on target {target}')

                label, classifier, embedding, transformer = classify_line(
                    options['test_on_line'], target
                )
                self.success(f'Successfully got label {label}')
            return

        for target in targets:
            self.info(f'Training model for target {target}')
            self.train_model_for_target(target, options['automatic'])

        if options['automatic']:
            ping_heartbeat("HEARTBEAT_TRAIN_PRUNING_URL")

    def train_model_for_target(self, target: Classifier.Target, automatic: bool):
        if automatic:
            last_training_at = Classifier.objects.filter(target=target) \
                .latest('created_at').created_at
            self.info(f'Last training was at {last_training_at} for target {target}')

            last_sentence_at = Sentence.objects.filter(updated_by__isnull=False) \
                .latest('updated_at').updated_at
            self.info(f'Last human-changed sentence updated at {last_sentence_at} '
                      f'for target {target}')

            if last_training_at > last_sentence_at:
                self.info(f'No need to retrain model for target {target}')
                return

        self.info(f'Building sentence dataset for target {target}...')
        sentence_dataset = build_sentence_dataset(target)
        self.info(f'Got {len(sentence_dataset)} sentences for target {target}')

        count_by_label = {}
        for sentence in sentence_dataset:
            label = extract_label(sentence, target)
            count_by_label[label] = count_by_label.get(label, 0) + 1
        for label, count in count_by_label.items():
            self.info(f'{count} sentences with label {label}')

        self.info(f'Training model for target {target}...')
        classifier = train_classifier(sentence_dataset, target)
        self.success(f'Successfully trained model with accuracy {classifier.accuracy}, '
                     f'with test size {classifier.test_size} for target {target}')

        if automatic:
            production_classifier = get_classifier(target)
            self.info(f'Production model accuracy: {production_classifier.accuracy}, '
                      f'test size: {production_classifier.test_size}')

            if classifier.accuracy > production_classifier.accuracy and \
                    is_significantly_different(classifier.accuracy, production_classifier.accuracy,
                                               classifier.test_size,
                                               production_classifier.test_size):
                self.success(f'New model is significantly better than production model')
                classifier.status = classifier.Status.PROD
                classifier.save()
            else:
                self.info(f'New model is not significantly better than production model')

        if classifier.status == classifier.Status.DRAFT:
            self.warning(f'WARNING: Trained model is still in draft status. '
                         f'You shall set it to prod in admin interface.')
        else:
            self.success(f'Model has now status {classifier.status}')
