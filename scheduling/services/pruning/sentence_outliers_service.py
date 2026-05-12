from registry.models import Sentence, SentenceModeration
from registry.models.base_moderation_models import ModerationStatus
from scheduling.workflows.pruning.extract.models import Action


##############
# MODERATION #
##############

def add_sentence_moderation(sentence: Sentence, other_action: Action):
    category = SentenceModeration.Category.ML_MISMATCH

    # check if moderation already exists
    if SentenceModeration.objects.filter(sentence=sentence, category=category).exists():
        return

    sentence_moderation = SentenceModeration(
        sentence=sentence,
        category=category,
        action=sentence.action,
        other_action=other_action,
        status=ModerationStatus.TO_VALIDATE,
    )
    sentence_moderation.save()


def remove_sentence_not_validated_moderation(sentence: Sentence):
    category = SentenceModeration.Category.ML_MISMATCH
    SentenceModeration.objects.filter(
        sentence=sentence, category=category,
    ).exclude(status=ModerationStatus.VALIDATED).delete()


#################
# V2 MODERATION #
#################

def add_sentence_v2_moderation(sentence: Sentence):
    category = SentenceModeration.Category.CONFESSION_OUTLIER

    # check if moderation already exists
    if SentenceModeration.objects.filter(sentence=sentence, category=category).exists():
        return

    sentence_moderation = SentenceModeration(
        sentence=sentence,
        category=category,
        status=ModerationStatus.TO_VALIDATE,
    )
    sentence_moderation.save()


def remove_sentence_not_validated_v2_moderation(sentence: Sentence):
    category = SentenceModeration.Category.CONFESSION_OUTLIER
    SentenceModeration.objects.filter(sentence=sentence, category=category).delete()
