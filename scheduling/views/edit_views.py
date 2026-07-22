import json

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponseNotFound
from django.shortcuts import render
from pydantic import ValidationError

from scheduling.forms.jsoneditor_form import JSONSchemaForm
from scheduling.models import Parsing
from scheduling.models.pruning_models import Pruning, Sentence
from scheduling.public_service import init_scheduling_for_sentences
from scheduling.services.parsing.edit_parsing_service import set_human_json
from scheduling.services.parsing.parsing_service import get_parsing_schedules_list
from scheduling.services.pruning.edit_pruning_service import set_human_indices, \
    get_pruning_human_pieces, get_colored_pieces_v2, set_v2_indices_as_human, \
    update_sentence_labels_with_request, TEMPORAL_COLORS, EVENT_MENTION_COLORS
from scheduling.services.pruning.prune_scraping_service import prune_pruning, \
    SentenceQualifyLineInterface
from scheduling.utils.html_utils import split_lines
from scheduling.workflows.parsing.schedules import SchedulesList, SCHEDULES_LIST_VERSION
from scheduling.workflows.pruning.extract_v2.qualify_line_interfaces import \
    DummyQualifyLineInterface


@login_required
@staff_member_required
def edit_pruning_human(request, pruning_uuid):
    try:
        pruning = Pruning.objects.get(uuid=pruning_uuid)
    except Pruning.DoesNotExist:
        return HttpResponseNotFound("Pruning not found")

    if request.method == "POST":
        new_indices = []
        for i in range(len(split_lines(pruning.extracted_html))):
            if request.POST.get(f"line-{i}", False):
                new_indices.append(i)

        set_human_indices(pruning, new_indices)

    pruning_human_pieces = get_pruning_human_pieces(pruning)

    return render(request, 'pages/edit_pruning_human.html', {
        'pruning': pruning,
        'pruning_human_pieces': pruning_human_pieces,
    })


@login_required
@permission_required("scheduling.change_sentence")
def edit_pruning_v2(request, pruning_uuid):
    try:
        pruning = Pruning.objects.get(uuid=pruning_uuid)
    except Pruning.DoesNotExist:
        return HttpResponseNotFound("Pruning not found")

    extracted_html = pruning.extracted_html

    if request.method == "POST":
        dummy_colored_pieces = get_colored_pieces_v2(extracted_html,
                                                     DummyQualifyLineInterface())
        modified_sentences = []
        for dummy_piece in dummy_colored_pieces:
            sentence_uuid = request.POST.get(f"sentence-uuid-{dummy_piece.id}")
            sentence = Sentence.objects.get(uuid=sentence_uuid)

            if update_sentence_labels_with_request(request, dummy_piece.id, sentence, pruning):
                modified_sentences.append(sentence)

        # Save pruning
        prune_pruning(pruning)

        if request.POST.get("set_as_human", '') == 'true':
            # Set human indices
            set_v2_indices_as_human(pruning)

        if modified_sentences:
            # re-prune affected prunings
            init_scheduling_for_sentences(modified_sentences)

    colored_pieces = get_colored_pieces_v2(extracted_html,
                                           SentenceQualifyLineInterface(pruning))

    return render(request, 'pages/edit_pruning_v2.html', {
        'pruning': pruning,
        'colored_pieces': colored_pieces,
        'event_mention_colors': EVENT_MENTION_COLORS,
        'temporal_colors': TEMPORAL_COLORS,
    })


@login_required
@permission_required("scheduling.change_sentence")
def edit_parsing(request, parsing_uuid):
    try:
        parsing = Parsing.objects.get(uuid=parsing_uuid)
    except Parsing.DoesNotExist:
        return HttpResponseNotFound("Parsing not found")

    schedules_list_as_json = None
    validation_error = None
    success = False

    if request.method == "POST":
        schedules_list_as_json = request.POST.get("json")
        schedules_list_as_dict = json.loads(schedules_list_as_json)
        try:
            schedules_list = SchedulesList(**schedules_list_as_dict)
            schedules_list.check_is_valid()
            set_human_json(parsing, schedules_list.model_dump(mode='json'), SCHEDULES_LIST_VERSION)
            success = True
        except ValidationError as e:
            validation_error = str(e)
        except ValueError as e:
            validation_error = str(e)

    if not schedules_list_as_json:
        schedules_list = get_parsing_schedules_list(parsing)
        schedules_list_as_json = schedules_list.model_dump_json()

    # This is a ugly hack since openai doesn't support format in the schema
    json_schema = json.loads(
        json.dumps(SchedulesList.model_json_schema())
        .replace('"description": "uniqueItems"', '"uniqueItems": true')
        .replace('description', 'format')
    )
    form = JSONSchemaForm(
        schema=json_schema,
        options={
            "theme": "bootstrap4",
            "enable_array_copy": True,
            "disable_edit_json": True,
            "disable_properties": True,
            "disable_array_delete_last_row": True,
            "prompt_before_delete": False,
            "no_additional_properties": True,
            "iconlib": "fontawesome5",
        },
        ajax=False,
        data={"json": schedules_list_as_json}
    )

    return render(request, 'pages/edit_parsing.html', {
        'parsing': parsing,
        'form': form,
        'validation_error': validation_error,
        'success': success,
    })
