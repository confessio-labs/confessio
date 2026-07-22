from registry.models.base_moderation_models import ModerationStatus
from scheduling.models.pruning_models import Sentence, SentenceModeration


#################
# V2 MODERATION #
#################

def add_sentence_v2_moderation(sentence: Sentence):
    category = SentenceModeration.Category.V2_OUTLIER

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
    category = SentenceModeration.Category.V2_OUTLIER
    SentenceModeration.objects.filter(sentence=sentence, category=category).delete()
