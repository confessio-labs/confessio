import re
from dataclasses import dataclass

from core.utils.async_utils import run_and_close
from core.utils.log_utils import info
from registry.models import Church
from registry.models.base_moderation_models import ModerationStatus
from scheduling.models import ParsingModeration, Parsing
from scheduling.models.pruning_models import Pruning
from scheduling.services.parsing.parsing_service import get_existing_parsing
from scheduling.services.parsing.church_desc_service import get_church_desc_by_id
from scheduling.services.scheduling.scheduling_service import get_websites_of_parsing
from scheduling.utils.hash_utils import hash_string_to_hex
from scheduling.utils.html_utils import stringify_html
from scheduling.workflows.parsing.llm_client import LLMClientInterface
from scheduling.workflows.parsing.parse_with_llm import parse_with_llm, get_prompt_template, \
    get_llm_client
from scheduling.workflows.parsing.schedules import SchedulesList, SCHEDULES_LIST_VERSION

TRUNCATION_LENGTH = 32
MAX_LENGTH_FOR_PARSING = 15000


##############
# TRUNCATION #
##############

def get_truncated_line(line: str) -> str:
    truncated_line = stringify_html(line)[:TRUNCATION_LENGTH]
    return f'[{truncated_line}...]'


def get_truncated_html(pruning: Pruning) -> str:
    extracted_html = str(re.sub(r"\n\s*", "", pruning.extracted_html))
    lines = extracted_html.split('<br>')

    truncated_lines = []
    last_index = None
    for index in pruning.get_pruned_indices():
        if last_index is not None and index != last_index + 1:
            truncated_lines.append(get_truncated_line(lines[last_index + 1]))
            if index - 1 > last_index + 1:
                if index - 2 > last_index + 1:
                    truncated_lines.append('[...]')
                truncated_lines.append(get_truncated_line(lines[index - 1]))
        truncated_lines.append(lines[index])
        last_index = index

    return '<br>'.join(truncated_lines)


##############
# MODERATION #
##############

def add_necessary_parsing_moderation(parsing: Parsing):
    category = get_category(parsing)
    needs_moderation = parsing_needs_moderation(parsing)

    # 1. we remove moderation of other category
    remove_parsing_moderation_of_other_category(parsing, category)

    # 2. we add moderation
    add_parsing_moderation(parsing, category, needs_moderation)


def add_parsing_moderation(parsing: Parsing, category: ParsingModeration.Category,
                           needs_moderation: bool):
    try:
        parsing_moderation = ParsingModeration.objects.filter(parsing=parsing,
                                                              category=category).get()
        if needs_moderation:
            if parsing_moderation.status != ModerationStatus.TO_VALIDATE:
                parsing_moderation.status = ModerationStatus.TO_VALIDATE
                parsing_moderation.save()
    except ParsingModeration.DoesNotExist:
        parsing_moderation = ParsingModeration(
            parsing=parsing,
            category=category,
            status=(ModerationStatus.TO_VALIDATE
                    if needs_moderation
                    else ModerationStatus.VALIDATED),
            diocese=None,
        )
        parsing_moderation.save()


def remove_parsing_moderation_of_other_category(parsing: Parsing,
                                                category: ParsingModeration.Category):
    ParsingModeration.objects.filter(parsing=parsing).exclude(category=category).delete()


def get_category(parsing: Parsing) -> ParsingModeration.Category:
    if parsing.llm_error_detail:
        return ParsingModeration.Category.LLM_ERROR

    if parsing.human_json is not None and parsing.human_json != parsing.llm_json:
        return ParsingModeration.Category.SCHEDULES_DIFFER

    return ParsingModeration.Category.NEW_SCHEDULES


def parsing_needs_moderation(parsing: Parsing):
    if parsing.human_json is not None and parsing.human_json == parsing.llm_json:
        return False

    if parsing.human_json is not None and parsing.human_json != parsing.llm_json:
        if ParsingModeration.objects.filter(
                parsing=parsing,
                category=ParsingModeration.Category.SCHEDULES_DIFFER,
                status=ModerationStatus.VALIDATED,
        ).exists():
            return False

    return True


####################
# MODERATION CLEAN #
####################

def remove_useless_moderation_for_parsing(parsing: Parsing):
    if get_websites_of_parsing(parsing):
        return

    info(f'deleting not validated moderation for parsing {parsing} since it has no '
         f'website any more')
    ParsingModeration.objects.filter(
        parsing=parsing,
    ).exclude(status=ModerationStatus.VALIDATED).delete()


#######################
# Parsing Preparation #
#######################

@dataclass
class ParsingPreparation:
    truncated_html: str
    truncated_html_hash: str
    church_desc_by_id: dict[int, str]
    llm_client: LLMClientInterface
    prompt_template: str
    prompt_template_hash: str
    parsing: Parsing | None
    needs_reparse: bool = True


def prepare_parsing(pruning: Pruning, churches: list[Church]) -> None | ParsingPreparation:
    truncated_html = get_truncated_html(pruning)
    truncated_html_hash = hash_string_to_hex(truncated_html) if truncated_html else None

    church_desc_by_id = get_church_desc_by_id(churches)

    if not truncated_html:
        info(f'No truncated html for pruning {pruning}')
        return None

    llm_client = get_llm_client()
    prompt_template = get_prompt_template()
    prompt_template_hash = hash_string_to_hex(prompt_template)

    # check the parsing does not already exist
    parsing = get_existing_parsing(truncated_html_hash, church_desc_by_id)
    if parsing \
            and parsing.llm_provider == llm_client.get_provider() \
            and parsing.llm_model == llm_client.get_model() \
            and parsing.prompt_template_hash == prompt_template_hash:

        # Adding necessary moderation if missing
        add_necessary_parsing_moderation(parsing)

        info(f'Parsing already exists for pruning {pruning}, parsing {parsing.uuid}')
        needs_reparse = False
    else:
        print(f'Preparing parsing for pruning {pruning.uuid}')
        needs_reparse = True

    return ParsingPreparation(truncated_html, truncated_html_hash, church_desc_by_id, llm_client,
                              prompt_template, prompt_template_hash, parsing, needs_reparse)


def prepare_reparsing(parsing: Parsing) -> ParsingPreparation:
    truncated_html = parsing.truncated_html
    truncated_html_hash = parsing.truncated_html_hash
    church_desc_by_id = parsing.church_desc_by_id

    llm_client = get_llm_client()
    prompt_template = get_prompt_template()
    prompt_template_hash = hash_string_to_hex(prompt_template)

    return ParsingPreparation(truncated_html, truncated_html_hash, church_desc_by_id, llm_client,
                              prompt_template, prompt_template_hash, parsing)


########
# MAIN #
########

def do_parse_pruning_for_website(pruning: Pruning, churches: list[Church]) -> Parsing | None:
    parsing_preparation = prepare_parsing(pruning, churches)
    if not parsing_preparation:
        return None

    if not parsing_preparation.needs_reparse:
        return parsing_preparation.parsing

    return parse_parsing_preparation(parsing_preparation)


def parse_parsing_preparation(parsing_preparation: ParsingPreparation) -> Parsing:
    truncated_html = parsing_preparation.truncated_html

    if len(truncated_html) > MAX_LENGTH_FOR_PARSING:
        info(f'No parsing above {MAX_LENGTH_FOR_PARSING}, got {len(truncated_html)},')
        schedules_list, llm_error_detail = None, "Truncated html too long"
    else:
        info(f'parsing with hash {parsing_preparation.truncated_html_hash}')
        llm_client = parsing_preparation.llm_client
        schedules_list, llm_error_detail = run_and_close(
            parse_with_llm(truncated_html,
                           parsing_preparation.church_desc_by_id,
                           parsing_preparation.prompt_template,
                           llm_client),
            llm_client.aclose,
        )

    return save_parsing(parsing_preparation, schedules_list, llm_error_detail)


def save_parsing(parsing_preparation: ParsingPreparation,
                 schedules_list: SchedulesList | None,
                 llm_error_detail: str | None) -> Parsing:
    llm_json = schedules_list.model_dump(mode="json") if schedules_list else None
    parsing = parsing_preparation.parsing
    llm_client = parsing_preparation.llm_client

    if parsing:
        parsing.llm_json = llm_json
        parsing.llm_json_version = SCHEDULES_LIST_VERSION
        parsing.llm_provider = llm_client.get_provider()
        parsing.llm_model = llm_client.get_model()
        parsing.prompt_template_hash = parsing_preparation.prompt_template_hash
        parsing.llm_error_detail = llm_error_detail
        parsing.save()
    else:
        parsing = Parsing(
            truncated_html=parsing_preparation.truncated_html,
            truncated_html_hash=parsing_preparation.truncated_html_hash,
            church_desc_by_id=parsing_preparation.church_desc_by_id,
            llm_json=llm_json,
            llm_json_version=SCHEDULES_LIST_VERSION,
            llm_provider=llm_client.get_provider(),
            llm_model=llm_client.get_model(),
            prompt_template_hash=parsing_preparation.prompt_template_hash,
            llm_error_detail=llm_error_detail,
        )
        parsing.save()

    add_necessary_parsing_moderation(parsing)

    return parsing
