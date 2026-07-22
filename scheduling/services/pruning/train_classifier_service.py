import torch  # noqa: F401  load torch before sklearn/scipy (macOS duplicate-OpenMP segfault guard)
from django.db.models import Q

from scheduling.models.pruning_models import Classifier, Sentence
from scheduling.utils.enum_utils import StringEnum
from scheduling.utils.stat_utils import MIN_DATASET_SIZE
from scheduling.workflows.pruning.extract_v2.models import Temporal, EventMention


def build_sentence_dataset(target: Classifier.Target) -> list[Sentence]:
    if target == Classifier.Target.TEMPORAL:
        human_qualified_dataset = Sentence.objects.filter(human_temporal__isnull=False).all()
        if len(human_qualified_dataset) >= MIN_DATASET_SIZE:
            return human_qualified_dataset

        print(f"Not enough human temporal sentences ({len(human_qualified_dataset)}), "
              f"using ML temporal sentences instead")
        return Sentence.objects.filter(Q(human_temporal__isnull=False)
                                       | Q(ml_temporal__isnull=False)).all()

    if target == Classifier.Target.CONFESSION:
        human_qualified_dataset = Sentence.objects.filter(
            human_confession__isnull=False).all()
        if len(human_qualified_dataset) >= MIN_DATASET_SIZE:
            return human_qualified_dataset

        print(f"Not enough human confession sentences ({len(human_qualified_dataset)}), "
              f"using ML confession sentences instead")
        return Sentence.objects.filter(Q(human_confession__isnull=False)
                                       | Q(ml_confession__isnull=False)).all()

    raise NotImplementedError(f'Target {target} is not supported for sentence dataset building')


def extract_label(sentence: Sentence, target: Classifier.Target) -> StringEnum:
    if target == Classifier.Target.TEMPORAL:
        if sentence.human_temporal is not None:
            return Temporal(sentence.human_temporal)
        if sentence.ml_temporal is not None:
            return Temporal(sentence.ml_temporal)
        raise ValueError(f'Sentence {sentence.uuid} has no temporal for target {target}')

    if target == Classifier.Target.CONFESSION:
        if sentence.human_confession is not None:
            return EventMention(sentence.human_confession)
        if sentence.ml_confession is not None:
            return EventMention(sentence.ml_confession)
        raise ValueError(f'Sentence {sentence.uuid} has no confession for target {target}')

    raise NotImplementedError(f'Target {target} is not supported for label extraction')


def set_label(sentence: Sentence, label: StringEnum, classifier: Classifier) -> None:
    if classifier.target == Classifier.Target.TEMPORAL:
        sentence.ml_temporal = label
        sentence.temporal_classifier = classifier
        return

    if classifier.target == Classifier.Target.CONFESSION:
        sentence.ml_confession = label
        sentence.confession_new_classifier = classifier
        return

    raise NotImplementedError(f'Target {classifier.target} is not supported for label setting')
