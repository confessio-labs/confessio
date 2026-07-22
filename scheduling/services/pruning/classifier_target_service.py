from typing import Type

from scheduling.models.pruning_models import Classifier
from scheduling.utils.enum_utils import StringEnum
from scheduling.workflows.pruning.extract.models import Action
from scheduling.workflows.pruning.extract_v2.models import Temporal, EventMention


def get_target_enum(target: Classifier.Target) -> Type[StringEnum]:
    if target == Classifier.Target.ACTION:
        return Action

    if target == Classifier.Target.TEMPORAL:
        return Temporal

    if target == Classifier.Target.CONFESSION:
        return EventMention

    raise NotImplementedError(f'Target {target} is not supported for different labels extraction')
