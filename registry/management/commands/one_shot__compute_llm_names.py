import asyncio
import os

from openai import AsyncOpenAI
from tqdm import tqdm

from core.management.abstract_command import AbstractCommand
from core.utils.async_utils import run_and_close
from registry.models import ChurchTrouverUneMesse, ChurchTrouverUneMesseLLMName
from scheduling.utils.hash_utils import hash_string_to_hex
from registry.services.church_llm_name_service import get_prompt_template_for_name, \
    get_completions_for_name, compute_churches_llm_name


class Command(AbstractCommand):
    help = "One shot command to compute church llm name."

    def handle(self, *args, **options):
        self.info('Starting one shot command to compute church llm name...')
        compute_churches_llm_name(max_churches=15000)
        # trouverunemesse_compute_churches_llm_name(max_churches=16000)
        self.success(f'Successfully computed church llm names.')


async def compute_churches_llm_name_by_batch(churches: list[ChurchTrouverUneMesse],
                                             prompt_template: str,
                                             client: AsyncOpenAI) -> None:
    original_church_name_by_id = {}
    for i, church in enumerate(churches):
        original_church_name_by_id[i] = church.original_name

    llm_output, llm_error_detail = await get_completions_for_name(
        original_church_name_by_id, prompt_template, client
    )
    if llm_output:
        new_church_names_by_id = {int(item.id): item.name
                                  for item in llm_output.church_ids_and_names}
        for i, church in enumerate(churches):
            new_church_name = new_church_names_by_id.get(i, None)
            if new_church_name:
                church_llm_name = ChurchTrouverUneMesseLLMName(
                    trouverunemesse_church=church,
                    prompt_template_hash=hash_string_to_hex(prompt_template),
                    original_name=church.original_name,
                    new_name=new_church_name
                )
                await church_llm_name.asave()
            else:
                print(f"Church {church.uuid} ({church.original_name}) has no new name computed,"
                      f" skipping.")
    else:
        if llm_error_detail:
            print(f"Error while computing LLM name for churches: {llm_error_detail}")
        else:
            print("No LLM output received, but no error detail provided.")


async def compute_in_parallel(chunks: list[list[ChurchTrouverUneMesse]], prompt_template: str,
                              client: AsyncOpenAI):
    chunk_of_chunks = [chunks[i: i + 20]
                       for i in range(0, len(chunks), 20)]
    for chunks in tqdm(chunk_of_chunks):
        tasks = [
            compute_churches_llm_name_by_batch(
                chunk, prompt_template, client
            ) for chunk in chunks
        ]
        await asyncio.gather(*tasks)


def trouverunemesse_compute_churches_llm_name(prompt_template: str | None = None,
                                              max_churches: int = 100) -> None:
    # print(json.dumps(LLMOutput.model_json_schema(), indent=2))
    # return

    if prompt_template is None:
        prompt_template = get_prompt_template_for_name()

    prompt_template_hash = hash_string_to_hex(prompt_template)
    already_computed_churches_uuids = ChurchTrouverUneMesse.objects.filter(
        llm_names__prompt_template_hash=prompt_template_hash
    ).values_list('uuid', flat=True)

    if len(already_computed_churches_uuids) >= max_churches:
        print(f'Skipping computation for {len(already_computed_churches_uuids)} churches,'
              f' already computed.')
        return

    not_computed_churches = ChurchTrouverUneMesse.objects.exclude(
        llm_names__prompt_template_hash=prompt_template_hash
    ).distinct()[:max_churches - len(already_computed_churches_uuids)]
    print(f'will compute {len(not_computed_churches)} churches')

    openai_api_key = os.getenv("OPENAI_API_KEY")
    client = AsyncOpenAI(api_key=openai_api_key)

    chunks = [not_computed_churches[i:i + 20]
              for i in range(0, len(not_computed_churches), 20)]
    run_and_close(compute_in_parallel(chunks, prompt_template, client), client.close)
