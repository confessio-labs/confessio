import json

from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponseNotFound, HttpResponseBadRequest
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from core.views import get_moderate_response, ModerationPostError, redirect_to_moderation
from crawling.models import CrawlingModeration
from registry.models import Website
from registry.models.base_moderation_models import ModerationStatus
from scheduling.models import ParsingModeration
from scheduling.models import SchedulingModeration, ValidatedSchedulesModeration
from scheduling.models.pruning_models import PruningModeration
from scheduling.models.pruning_models import SentenceModeration
from scheduling.services.merging.validated_schedules_service import \
    validate_website_indexed_schedules, build_website_validated_schedules_comparison
from scheduling.services.parsing.edit_parsing_service import set_llm_json_as_human_json, \
    on_parsing_human_validation, ParsingValidationError
from scheduling.services.parsing.parsing_service import get_schedules_list_from_dict
from scheduling.services.parsing.reparse_parsing_service import reparse_parsing
from scheduling.services.pruning.edit_pruning_service import get_single_line_colored_piece, \
    TEMPORAL_COLORS, EVENT_MENTION_COLORS, on_pruning_human_validation, \
    update_sentence_labels_with_request
from scheduling.services.pruning.edit_pruning_service import set_v2_indices_as_human
from scheduling.services.pruning.prune_scraping_service import SentenceQualifyLineInterface, \
    MLSentenceQualifyLineInterface
from scheduling.services.scheduling.scheduling_process_service import init_scheduling
from scheduling.services.scheduling.scheduling_service import get_parsing_moderation_of_pruning
from scheduling.workflows.pruning.extract.models import Source
from scheduling.workflows.pruning.extract_v2.split_content import create_line_and_tag_v2


@login_required
@permission_required("scheduling.change_sentence")
def moderate_pruning(request, category, status, diocese_slug, moderation_uuid=None):
    return get_moderate_response(request, category, 'pruning', status, diocese_slug,
                                 PruningModeration, moderation_uuid,
                                 create_pruning_moderation_context,
                                 pruning_moderation_post_process)


def create_pruning_moderation_context(moderation: PruningModeration) -> dict:
    pruning = moderation.pruning
    assert pruning is not None

    differs_by_index = []
    for i in range(len(pruning.extracted_html.split('<br>\n'))):
        i_in_human = None if pruning.human_indices is None else i in pruning.human_indices
        i_in_v2 = None if pruning.v2_indices is None else i in pruning.v2_indices

        values = list(filter(lambda b: b is not None, [i_in_human, i_in_v2]))
        differs_by_index.append(len(set(values)) > 1)

    human_lines_and_colors = []
    if pruning.human_indices is not None:
        for i, line in enumerate(pruning.extracted_html.split('<br>\n')):
            color = '' if i in pruning.human_indices else 'text-warning'
            differs = 'fw-bold display-5' if differs_by_index[i] else ''
            human_lines_and_colors.append((line, color, differs))

    v2_lines_and_colors = []
    if pruning.v2_indices is not None:
        for i, line in enumerate(pruning.extracted_html.split('<br>\n')):
            color = '' if i in pruning.v2_indices else 'text-warning'
            differs = 'fw-bold display-5' if differs_by_index[i] else ''
            v2_lines_and_colors.append((line, color, differs))

    parsing_moderation = get_parsing_moderation_of_pruning(pruning)

    return {
        'pruning': pruning,
        'human_lines_and_colors': human_lines_and_colors,
        'v2_lines_and_colors': v2_lines_and_colors,
        'parsing_moderation': parsing_moderation,
    }


def pruning_moderation_post_process(request, moderation: PruningModeration) -> bool:
    on_pruning_human_validation(moderation.pruning)
    return True


@login_required
@permission_required("scheduling.change_sentence")
def moderate_sentence(request, category, status, diocese_slug, moderation_uuid=None):
    return get_moderate_response(request, category, 'sentence', status, diocese_slug,
                                 SentenceModeration, moderation_uuid,
                                 create_sentence_moderation_context,
                                 sentence_moderation_post_process)


def create_sentence_moderation_context(moderation: SentenceModeration) -> dict:
    assert moderation.sentence is not None

    line_and_tag_human = create_line_and_tag_v2(moderation.sentence.line,
                                                SentenceQualifyLineInterface())
    colored_piece_human = get_single_line_colored_piece(
        line_and_tag_human, Source.HUMAN, i=1, do_show=True)
    line_and_tag_ml = create_line_and_tag_v2(moderation.sentence.line,
                                             MLSentenceQualifyLineInterface())
    colored_piece_ml = get_single_line_colored_piece(
        line_and_tag_ml, Source.ML, i=2, do_show=True)

    return {
        'sentence': moderation.sentence,
        'colored_pieces': [colored_piece_human, colored_piece_ml],
        'temporal_colors': TEMPORAL_COLORS,
        'event_mention_colors': EVENT_MENTION_COLORS,
    }


def sentence_moderation_post_process(request, moderation: SentenceModeration) -> bool:
    if 'update_human_labels' in request.POST:
        update_sentence_labels_with_request(request, "1", moderation.sentence, None)
        return False
    return True


@login_required
@permission_required("scheduling.change_sentence")
def moderate_parsing(request, category, status, diocese_slug, moderation_uuid=None):
    return get_moderate_response(request, category, 'parsing', status, diocese_slug,
                                 ParsingModeration, moderation_uuid,
                                 create_parsing_moderation_context,
                                 parsing_moderation_post_process)


def create_parsing_moderation_context(moderation: ParsingModeration) -> dict:
    parsing = moderation.parsing
    assert parsing is not None

    truncated_html = parsing.truncated_html
    if parsing.llm_json:
        llm_schedules_list = get_schedules_list_from_dict(parsing.llm_json,
                                                          parsing.llm_json_version)
    else:
        llm_schedules_list = None

    if parsing.human_json:
        human_schedules_list = get_schedules_list_from_dict(parsing.human_json,
                                                            parsing.human_json_version)
    else:
        human_schedules_list = None

    church_desc_by_id_json = json.dumps(parsing.church_desc_by_id, indent=2, ensure_ascii=False)

    return {
        'parsing': parsing,
        'church_desc_by_id_json': church_desc_by_id_json,
        'truncated_html': truncated_html,
        'llm_schedules_list': llm_schedules_list,
        'human_schedules_list': human_schedules_list,
    }


def parsing_moderation_post_process(request, moderation: ParsingModeration) -> bool:
    if 'reparse_parsing' in request.POST:
        reparse_parsing(moderation.parsing)
        return False

    try:
        on_parsing_human_validation(moderation)
    except ParsingValidationError as e:
        raise ModerationPostError(response=HttpResponseBadRequest(str(e)))

    return True


@login_required
@permission_required("scheduling.change_sentence")
def moderate_scheduling(request, category, status, diocese_slug, moderation_uuid=None):
    return get_moderate_response(request, category, 'scheduling', status, diocese_slug,
                                 SchedulingModeration, moderation_uuid,
                                 create_scheduling_moderation_context)


def create_scheduling_moderation_context(moderation: SchedulingModeration) -> dict:
    return {
        'website': moderation.website,
    }


@login_required
@permission_required("scheduling.change_sentence")
def moderate_validated_schedules(request, category, status, diocese_slug, moderation_uuid=None):
    return get_moderate_response(request, category, 'validated_schedules', status, diocese_slug,
                                 ValidatedSchedulesModeration, moderation_uuid,
                                 create_validated_schedules_moderation_context)


def create_validated_schedules_moderation_context(
        moderation: ValidatedSchedulesModeration) -> dict:
    comparison = build_website_validated_schedules_comparison(moderation.website)

    return {
        'website': moderation.website,
        'comparison': comparison,
    }


@login_required
@permission_required("scheduling.change_sentence")
def moderate_erase_human_by_llm(request, parsing_moderation_uuid=None):
    try:
        parsing_moderation = ParsingModeration.objects.get(uuid=parsing_moderation_uuid)
    except ParsingModeration.DoesNotExist:
        return HttpResponseNotFound(f'parsing moderation not found with uuid '
                                    f'{parsing_moderation_uuid}')

    parsing = parsing_moderation.parsing
    if parsing.llm_json is None:
        return HttpResponseBadRequest(f'Can not erase human by llm because parsing '
                                      f'{parsing.uuid} does not have llm_json')

    set_llm_json_as_human_json(parsing)

    return redirect_to_moderation(parsing_moderation, parsing_moderation.category, 'parsing',
                                  parsing_moderation.status,
                                  parsing_moderation.get_diocese_slug())


@login_required
@permission_required("scheduling.change_sentence")
def moderate_set_v2_indices_as_human_by(request, pruning_moderation_uuid=None):
    try:
        pruning_moderation = PruningModeration.objects.get(uuid=pruning_moderation_uuid)
    except PruningModeration.DoesNotExist:
        return HttpResponseNotFound(f'pruning moderation not found with uuid '
                                    f'{pruning_moderation_uuid}')

    pruning = pruning_moderation.pruning
    if pruning.v2_indices is None:
        return HttpResponseBadRequest(f'Can not erase human by llm because parsing '
                                      f'{pruning.uuid} does not have llm_json')

    set_v2_indices_as_human(pruning)

    return redirect_to_moderation(pruning_moderation, pruning_moderation.category, 'pruning',
                                  pruning_moderation.status,
                                  pruning_moderation.get_diocese_slug())


@login_required
@permission_required("scheduling.change_sentence")
@require_POST
def validate_schedules_for_website(request, website_uuid=None):
    try:
        website = Website.objects.get(uuid=website_uuid)
    except PruningModeration.DoesNotExist:
        return HttpResponseNotFound(f'website not found with uuid {website_uuid}')

    assert request.user is not None

    try:
        scheduling_moderation = SchedulingModeration.objects.get(website=website)
        if scheduling_moderation.status != ModerationStatus.VALIDATED:
            scheduling_moderation.validate(request.user)
    except SchedulingModeration.DoesNotExist:
        pass
    try:
        crawling_moderation = CrawlingModeration.objects.get(website=website)
        if crawling_moderation.status != ModerationStatus.VALIDATED:
            crawling_moderation.validate(request.user)
    except CrawlingModeration.DoesNotExist:
        pass

    validate_website_indexed_schedules(website, request.user)
    init_scheduling(website)

    next_url = request.POST.get('next', '/')
    return redirect(next_url)
