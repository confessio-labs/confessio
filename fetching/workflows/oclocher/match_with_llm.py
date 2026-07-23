import os
from typing import TYPE_CHECKING

from pydantic import ValidationError

if TYPE_CHECKING:
    # openai costs ~0.24 s to import and this module is only ever used by the worker, but it is
    # reachable from the server startup path (scheduling.public_service -> ... -> here), so it is
    # imported lazily, inside the functions that need it.
    from openai import OpenAI
    from openai.types.chat import ChatCompletionMessageParam

from fetching.workflows.oclocher.oclocher_matrix import OClocherMatrix
from scheduling.utils.hash_utils import hash_string_to_hex
from core.utils.llm_utils import LLMProvider


def get_prompt_template():
    return """Please help me match locations (Source B) to churches (Source A).
Please return a json dict with key "mappings", a list of json with two fields:
- [Source B] location_id (int)
- [Source A] church_id (int or null)
Please return as many items as Source B locations.

Example:
Source A churches:
1: St. Peter's Church
2: Church of the Holy Trinity
Source B locations:
10: St. John's Parish
20: Holy Trinity Church
30: St. James' Cathedral
Would output:
{{"mappings": [
    {{"location_id": 10, "church_id": null}},
    {{"location_id": 20, "church_id": 2}},
    {{"location_id": 30, "church_id": null}}
]}}

The Source A churches ids to consider:
{church_description}

The Source B locations ids to consider:
{location_description}"""


def get_church_desc(church_desc_by_id: dict[int, str]):
    return "\n".join(f'{church_id}: {desc}'
                     for church_id, desc in church_desc_by_id.items())


def build_prompt_text(prompt_template: str,
                      church_desc_by_id: dict[int, str],
                      location_desc_by_id: dict[int, str]) -> str:
    church_description = "\n".join(f'{church_id}: {desc}'
                                   for church_id, desc in church_desc_by_id.items())
    location_description = "\n".join(f'{location_id}: {desc}'
                                     for location_id, desc in location_desc_by_id.items())

    return prompt_template.format(church_description=church_description,
                                  location_description=location_description)


def build_input_messages(prompt_template: str,
                         church_desc_by_id: dict[int, str],
                         location_desc_by_id: dict[int, str]
                         ) -> list['ChatCompletionMessageParam']:
    from openai.types.chat import ChatCompletionUserMessageParam, \
        ChatCompletionContentPartTextParam

    return [
        ChatCompletionUserMessageParam(
            role="user",
            content=[
                ChatCompletionContentPartTextParam(
                    type="text",
                    text=build_prompt_text(prompt_template, church_desc_by_id, location_desc_by_id)
                )
            ]
        )
    ]


def get_openai_client() -> 'OpenAI':
    from openai import OpenAI

    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def run_llm_completion(
        llm_model: str,
        prompt_template: str,
        church_desc_by_id: dict[int, str],
        location_desc_by_id: dict[int, str]
) -> tuple[OClocherMatrix | None, str | None]:
    from openai import BadRequestError

    openai_client = get_openai_client()
    try:
        temperature_args = {'temperature': 0.0} if llm_model != 'o3' else {}
        response = openai_client.chat.completions.parse(
            model=llm_model,
            messages=build_input_messages(prompt_template, church_desc_by_id, location_desc_by_id),
            response_format=OClocherMatrix,
            **temperature_args
        )
    except BadRequestError as e:
        print(e)
        return None, str(e)
    except ValidationError as e:
        print(e)
        return None, str(e)

    message = response.choices[0].message
    llm_matrix = message.parsed
    if not llm_matrix:
        return None, message.refusal

    if not llm_matrix.mappings:
        return None, 'LLM did not return any match'

    if len(llm_matrix.mappings) != len(location_desc_by_id):
        return None, (f'LLM did not return a match for each location, expected '
                      f'{len(location_desc_by_id)} but got '
                      f'{len(llm_matrix.mappings)}')

    for location_church_mapping in llm_matrix.mappings:
        church_id = location_church_mapping.church_id
        location_id = location_church_mapping.location_id
        if church_id is not None and church_id not in church_desc_by_id:
            return None, (f'Invalid church_id id {church_id} in '
                          f'{llm_matrix.mappings=}')
        if location_id not in location_desc_by_id:
            return None, (f'Invalid location id {location_id} in '
                          f'{llm_matrix.mappings=}')

    return llm_matrix, None


def match_oclocher_with_llm(
        church_desc_by_id: dict[int, str],
        location_desc_by_id: dict[int, str]
) -> tuple[OClocherMatrix, str | None, LLMProvider, str, str]:
    llm_provider = LLMProvider.OPENAI
    llm_model = 'gpt-4.1'
    prompt_template = get_prompt_template()
    prompt_template_hash = hash_string_to_hex(prompt_template)

    llm_matrix, llm_error_detail = run_llm_completion(
        llm_model,
        prompt_template,
        church_desc_by_id,
        location_desc_by_id
    )

    return llm_matrix, llm_error_detail, llm_provider, llm_model, prompt_template_hash
