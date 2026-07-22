from uuid import UUID

from pydantic import BaseModel

from scheduling.models.pruning_models import Sentence, Pruning, Classifier
from scheduling.public_service import init_scheduling_for_pruning
from scheduling.services.pruning.prune_scraping_service import add_necessary_moderation_v2
from scheduling.services.pruning.train_classifier_service import extract_label
from scheduling.utils.enum_utils import StringEnum
from scheduling.utils.html_utils import split_lines, replace_link_by_their_content
from scheduling.workflows.pruning.extract_v2.models import EventMention, Temporal
from scheduling.workflows.pruning.extract_v2.prune_lines_v2 import get_pruned_lines_indices_v2
from scheduling.workflows.pruning.extract_v2.qualify_line_interfaces import BaseQualifyLineInterface
from scheduling.workflows.pruning.extract_v2.split_content import split_and_tag_v2, LineAndTagV2


#################
# HUMAN INDICES #
#################

class PruningHumanPiece(BaseModel):
    id: str
    do_show: bool
    text_without_link: str


def get_pruning_human_pieces(pruning: Pruning) -> list[PruningHumanPiece]:
    pruning_human_pieces = []
    for i, line in enumerate(split_lines(pruning.extracted_html)):
        text_without_link = replace_link_by_their_content(line)
        pruning_human_pieces.append(PruningHumanPiece(
            id=f'{i}',
            do_show=i in pruning.get_pruned_indices(),
            text_without_link=text_without_link
        ))

    return pruning_human_pieces


def set_human_indices(pruning: Pruning, indices: list[int]):
    needs_reschedule = pruning.get_pruned_indices() != indices

    pruning.human_indices = indices
    pruning.save()

    if needs_reschedule:
        init_scheduling_for_pruning(pruning)

    add_necessary_moderation_v2(pruning)


#################
# ML INDICES V2 #
#################

EVENT_MENTION_COLORS = {
    EventMention.EVENT: 'success',
    EventMention.NEUTRAL: 'info',
    EventMention.OTHER: 'black',
}

TEMPORAL_COLORS = {
    Temporal.NONE: 'gray-500',
    Temporal.SCHED: 'tertiary',
    Temporal.SPEC: 'purple',
}


class ColoredPieceV2(BaseModel):
    id: str
    do_show: bool
    text: str
    color: str
    event_mention: EventMention
    temporal: Temporal
    source_icon: str
    sentence_uuid: UUID | None


class Source(StringEnum):
    HUMAN = "human"
    ML = "ml"


def get_colored_pieces_v2(extracted_html: str, qualify_line_interface: BaseQualifyLineInterface
                          ) -> list[ColoredPieceV2]:
    lines_and_tags = split_and_tag_v2(extracted_html, qualify_line_interface)

    # used for debugging
    # import json
    # print(json.dumps([m.model_dump(mode='json') for m in lines_and_tags]))

    kept_indices = sum(get_pruned_lines_indices_v2(lines_and_tags), [])

    colored_pieces = []
    for i, line_and_tag in enumerate(lines_and_tags):
        do_show = i in kept_indices
        sentence = Sentence.objects.get(uuid=line_and_tag.sentence_uuid) \
            if line_and_tag.sentence_uuid else None
        source = Source.HUMAN if sentence and sentence.human_confession is not None \
            else Source.ML

        colored_pieces.append(get_single_line_colored_piece(line_and_tag, source, i, do_show))

    return colored_pieces


def get_single_line_colored_piece(line_and_tag: LineAndTagV2,
                                  source: Source,
                                  i: int, do_show: bool) -> ColoredPieceV2:
    source_icons = {
        Source.HUMAN: 'fas fa-user',
        Source.ML: 'fas fa-robot',
    }

    assert len(line_and_tag.temporal_tags) <= 1
    if line_and_tag.temporal_tags == {Temporal.SPEC}:
        temporal = Temporal.SPEC
    elif line_and_tag.temporal_tags == {Temporal.SCHED}:
        temporal = Temporal.SCHED
    else:
        temporal = Temporal.NONE

    assert len(line_and_tag.event_mention_tags) <= 1
    if line_and_tag.event_mention_tags == {EventMention.EVENT}:
        event_mention = EventMention.EVENT
    elif line_and_tag.event_mention_tags == {EventMention.OTHER}:
        event_mention = EventMention.OTHER
    else:
        event_mention = EventMention.NEUTRAL

    return ColoredPieceV2(
        id=f'{i}',
        do_show=do_show,
        text=line_and_tag.line,
        color='' if do_show else 'text-warning',
        event_mention=event_mention,
        temporal=temporal,
        source_icon=source_icons[source],
        sentence_uuid=line_and_tag.sentence_uuid,
    )


def update_sentence_labels_with_request(request, piece_id: str, sentence: Sentence,
                                        pruning: Pruning | None) -> bool:
    new_temporal = Temporal(request.POST.get(f"temporal-{piece_id}"))
    new_event_mention = EventMention(request.POST.get(f"event-mention-{piece_id}"))

    if extract_label(sentence, Classifier.Target.TEMPORAL) != new_temporal \
            or extract_label(sentence, Classifier.Target.CONFESSION) != new_event_mention:
        sentence.updated_by = request.user
        sentence.updated_on_pruning = pruning
        sentence.human_temporal = new_temporal
        sentence.human_confession = new_event_mention
        sentence.save()

        return True

    return False


def set_v2_indices_as_human(pruning: Pruning):
    set_human_indices(pruning, pruning.v2_indices)


####################
# HUMAN VALIDATION #
####################

def on_pruning_human_validation(pruning: Pruning):
    set_v2_indices_as_human(pruning)
