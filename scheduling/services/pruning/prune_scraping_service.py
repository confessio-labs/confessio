from typing import Optional
from uuid import UUID

from django.db import IntegrityError, transaction

from core.utils.log_utils import info
from registry.models.base_moderation_models import ModerationStatus
from scheduling.models.pruning_models import PruningModeration, Pruning, Sentence
from scheduling.services.pruning.classify_sentence_service import classify_and_create_sentence
from scheduling.workflows.pruning.extract.action_interfaces import BaseActionInterface
from scheduling.workflows.pruning.extract.extract_content import \
    extract_paragraphs_lines_and_indices
from scheduling.workflows.pruning.extract_interface import ExtractMode
from scheduling.workflows.pruning.extract_v2.extract_content import \
    extract_paragraphs_lines_and_indices_v2
from scheduling.workflows.pruning.extract_v2.models import EventMention, Temporal
from scheduling.workflows.pruning.extract_v2.qualify_line_interfaces import BaseQualifyLineInterface
from scheduling.workflows.pruning.extract.models import Action, Source


######################
# TAGGING WITH DB V1 #
######################

class SentenceFromDbActionInterface(BaseActionInterface):
    def __init__(self, pruning: Pruning):
        self.pruning = pruning

    def get_action(self, stringified_line: str) -> tuple[Action, Source, UUID]:
        sentence = self.get_sentence(stringified_line)
        sentence.prunings.add(self.pruning)

        return Action(sentence.action), Source(sentence.source), sentence.uuid

    def get_sentence(self, stringified_line: str) -> Sentence:
        try:
            return Sentence.objects.get(line=stringified_line)
        except Sentence.DoesNotExist:
            return classify_and_create_sentence(stringified_line, self.pruning)


######################
# TAGGING WITH DB V2 #
######################

class SentenceQualifyLineInterface(BaseQualifyLineInterface):
    def __init__(self, pruning: Pruning | None = None):
        self.pruning = pruning

    def get_temporal_and_event_mention_tags(
            self, stringified_line: str) -> tuple[set[Temporal], set[EventMention], UUID | None]:
        sentence = self.get_sentence(stringified_line)
        if self.pruning:
            sentence.prunings.add(self.pruning)

        if sentence.human_temporal is not None or sentence.ml_temporal is not None:
            temporal_tags = {Temporal(sentence.human_temporal or sentence.ml_temporal)}
        else:
            raise ValueError(f'Sentence {sentence.uuid} has no human '
                             f'temporal nor ML temporal')

        if sentence.human_confession is not None or sentence.ml_confession is not None:
            event_mention_tags = {EventMention(sentence.human_confession or sentence.ml_confession)}
        else:
            raise ValueError(f'Sentence {sentence.uuid} has no human '
                             f'confession nor ML confession')

        return temporal_tags, event_mention_tags, sentence.uuid

    def get_sentence(self, stringified_line: str) -> Sentence:
        try:
            return Sentence.objects.get(line=stringified_line)
        except Sentence.DoesNotExist:
            if not self.pruning:
                raise ValueError(f'Sentence does not exist for line {stringified_line}')
            return classify_and_create_sentence(stringified_line, self.pruning)


class MLSentenceQualifyLineInterface(SentenceQualifyLineInterface):
    def get_temporal_and_event_mention_tags(
            self, stringified_line: str) -> tuple[set[Temporal], set[EventMention], UUID | None]:
        sentence = self.get_sentence(stringified_line)
        if self.pruning:
            sentence.prunings.add(self.pruning)

        if sentence.ml_temporal is not None:
            temporal_tags = {Temporal(sentence.ml_temporal)}
        else:
            raise ValueError(f'Sentence {sentence.uuid} has no ML temporal')

        if sentence.ml_confession is not None:
            event_mention_tags = {EventMention(sentence.ml_confession)}
        else:
            raise ValueError(f'Sentence {sentence.uuid} has no ML confession')

        return temporal_tags, event_mention_tags, sentence.uuid


##############################
# REPRUNE AFFECTED SCRAPINGS #
##############################

def remove_pruning_moderation_if_orphan(pruning: Pruning):
    if not pruning.scrapings.exists() and not pruning.images.exists():
        info(f'deleting not validated moderation for pruning {pruning} since it has no scraping '
             f'nor image any more')
        PruningModeration.objects.filter(
            pruning=pruning,
        ).exclude(status=ModerationStatus.VALIDATED).delete()


##############
# MODERATION #
##############

def get_current_moderation(pruning: Pruning,
                           category: PruningModeration.Category) -> Optional[PruningModeration]:
    try:
        return PruningModeration.objects.get(pruning=pruning, category=category)
    except PruningModeration.DoesNotExist:
        return None


def delete_moderation(pruning: Pruning, category: PruningModeration.Category) -> None:
    PruningModeration.objects.filter(pruning=pruning, category=category).delete()


def add_new_moderation(pruning: Pruning, category):
    if get_current_moderation(pruning, category) is not None:
        # moderation already exists, we do not need to create a new one
        return

    moderation = PruningModeration(
        pruning=pruning,
        category=category,
        diocese=pruning.get_diocese(),
        status=ModerationStatus.TO_VALIDATE,
    )
    try:
        with transaction.atomic():
            moderation.save()
    except IntegrityError:
        info(f'PruningModeration for pruning {pruning} and category {category} '
             f'already exists, skipping creation')


def add_necessary_moderation(pruning: Pruning):
    category = PruningModeration.Category.NEW_PRUNED_HTML
    current_moderation = get_current_moderation(pruning, category)

    if pruning.ml_indices == pruning.human_indices:
        if current_moderation is not None:
            current_moderation.delete()
        return

    # 1. If pruning has already moderation
    if current_moderation is not None:
        if current_moderation.status != ModerationStatus.VALIDATED:
            # moderation is not validated yet, we just keep it
            return

        # moderation has been validated
        current_moderation.delete()

    add_new_moderation(pruning, category)


def add_necessary_moderation_v2(pruning: Pruning):
    if pruning.v2_indices == pruning.human_indices \
            or (pruning.human_indices is None and pruning.v2_indices == pruning.ml_indices):
        delete_moderation(pruning, PruningModeration.Category.V2_DIFF_HUMAN)
        delete_moderation(pruning, PruningModeration.Category.V2_DIFF_V1)
        return

    if pruning.human_indices is not None and pruning.v2_indices != pruning.human_indices:
        add_new_moderation(pruning, PruningModeration.Category.V2_DIFF_HUMAN)
        delete_moderation(pruning, PruningModeration.Category.V2_DIFF_V1)
        return

    delete_moderation(pruning, PruningModeration.Category.V2_DIFF_HUMAN)
    add_new_moderation(pruning, PruningModeration.Category.V2_DIFF_V1)


########
# MAIN #
########

def prune_pruning(pruning: Pruning) -> ():
    assert pruning.extracted_html, 'Pruning must have not empty extracted_html'

    # V1
    paragraphs = extract_paragraphs_lines_and_indices(pruning.extracted_html,
                                                      SentenceFromDbActionInterface(pruning),
                                                      ExtractMode.PRUNE)
    ml_indices = sum([indices for _, indices in paragraphs], [])

    if ml_indices != pruning.ml_indices:
        pruning.ml_indices = ml_indices
        pruning.save()

        add_necessary_moderation(pruning)

    # V2
    paragraphs_v2 = extract_paragraphs_lines_and_indices_v2(pruning.extracted_html,
                                                            SentenceQualifyLineInterface(pruning),
                                                            ExtractMode.PRUNE)
    v2_indices = sum([indices for _, indices in paragraphs_v2], [])
    if v2_indices != pruning.v2_indices:
        pruning.v2_indices = v2_indices
        pruning.save()

        add_necessary_moderation_v2(pruning)


def create_pruning(extracted_html: Optional[str]) -> Optional[Pruning]:
    if not extracted_html:
        return None

    try:
        pruning = Pruning.objects.get(extracted_html=extracted_html)
    except Pruning.DoesNotExist:
        pruning = Pruning(
            extracted_html=extracted_html,
        )
        pruning.save()

    return pruning
