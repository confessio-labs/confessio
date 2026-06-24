import asyncio
import json
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI, BadRequestError
from pydantic import ValidationError, BaseModel
from tqdm import tqdm

from core.utils.async_utils import run_and_close
from registry.models import Church
from registry.models.one_shot_models import ChurchLLMName
from scheduling.utils.hash_utils import hash_string_to_hex

BATCH_SIZE = 20
PARALLELING_SIZE = 20


def get_prompt_template_for_name():
    return """\
Corrige les noms de lieux de culte suivants en fonction des règles de nommage ci-dessous.

Liste des types d'établissements :
Basilique
Cathédrale
Chapelle
Église
Abbatiale
Maison de retraite
Maison paroissiale
Maison diocésaine
Ehpad

Règles de nommage :
1. Si le type de bâtiment n'est pas au début du nom, ajoute-le avec une majuscule initiale.

2. S'il y a un nom entre parenthèse à la fin, c'est un lieu dit.
Retire les parenthèses et ajoute un mot de liaison pour le lier au reste du nom.

3. Transforme les "œ" et en "oe", mais n'omets pas les accents.

4. Mets des majuscules aux mots significatifs,
mais les mots de liaison (comme "et", "de", "ou") doivent être en minuscules.

5. Le nom de l'église doit respecter la règle suivante :
entre "Saint" et le nom du saint, il y a un tiret,
mais entre plusieurs saints, il ne doit pas y avoir de tiret
(exemple : "Église Saint-Denis et Saint-Blaise").
Il n'y a pas de tiret avant un chiffre romain.

7. Aéroport, Maison de retraite,... Garder ce genre d'information dans le nom.

8. Si le nom est un nom de saint seul (comme Saint Aubin),
ajouter le type d'établissement Église est suffisant.

9. Ne jamais ajouter d'information au nom,
sauf si cela découle explicitement d’une règle ci-dessus (notamment la règle 8).

Exemples :
"Saint Irénée" -> "Église Saint-Irénée"
"La Rédemption" -> "Église de la Rédemption"
"Nativité de la Vierge Marie" -> "Église de la Nativité de la Vierge Marie"
"Saint Jean Baptiste" -> "Église Saint-Jean-Baptiste"
"Chapelle Valpré (centre Assomptionniste)" -> "Chapelle Valpré du Centre Assomptionniste"
"Chapelle des Jésuites (Chapelle St Ignace)" -> "Chapelle des Jésuites dite Chapelle Saint-Ignace"
"Assomption (Colombier)" -> "Église de l'Assomption à Colombier"


Voici les noms des lieux de culte à corriger :
{original_church_name_by_id_pretty_json}

Retourne une liste de dictionnaires avec les id et name (le nom corrigé) de chaque lieu de culte.
"""


class ChurchIdAndName(BaseModel):
    id: int
    name: str


class LLMOutput(BaseModel):
    church_ids_and_names: list[ChurchIdAndName]


def build_prompt_text(prompt_template: str,
                      original_church_name_by_id: dict[int, str]) -> str:
    return prompt_template.format(
        original_church_name_by_id_pretty_json=json.dumps(original_church_name_by_id, indent=2))


def build_input_messages(prompt_template: str,
                         original_church_name_by_id: dict[int, str]) -> list[dict]:
    return [
        {
            "role": "user",
            "content": build_prompt_text(prompt_template, original_church_name_by_id)
        }
    ]


async def get_completions_for_name(original_church_name_by_id: dict[int, str],
                                   prompt_template: str, client: AsyncOpenAI
                                   ) -> tuple[LLMOutput | None, str | None]:
    messages = build_input_messages(prompt_template, original_church_name_by_id)

    try:
        response = await client.responses.parse(
            model='gpt-4.1',
            input=messages,
            text_format=LLMOutput,
            temperature=0.0,
        )
    except BadRequestError as e:
        print(e)
        return None, str(e)
    except ValidationError as e:
        print(e)
        return None, str(e)

    return response.output_parsed, None


async def compute_churches_llm_name_by_batch(churches: list[Church], prompt_template: str,
                                             client: AsyncOpenAI) -> None:
    original_church_name_by_id = {}
    for i, church in enumerate(churches):
        original_church_name_by_id[i] = church.name

    llm_output, llm_error_detail = await get_completions_for_name(
        original_church_name_by_id, prompt_template, client
    )
    if llm_output:
        new_church_names_by_id = {int(item.id): item.name
                                  for item in llm_output.church_ids_and_names}
        for i, church in enumerate(churches):
            new_church_name = new_church_names_by_id.get(i, None)
            if new_church_name:
                church_llm_name = ChurchLLMName(
                    church=church,
                    prompt_template_hash=hash_string_to_hex(prompt_template),
                    original_name=church.name,
                    new_name=new_church_name
                )
                await church_llm_name.asave()
            else:
                print(f"Church {church.uuid} ({church.name}) has no new name computed, skipping.")
    else:
        if llm_error_detail:
            print(f"Error while computing LLM name for churches: {llm_error_detail}")
        else:
            print("No LLM output received, but no error detail provided.")


async def compute_in_parallel(chunks: list[list[Church]], prompt_template: str,
                              client: AsyncOpenAI):
    chunk_of_chunks = [chunks[i: i + PARALLELING_SIZE]
                       for i in range(0, len(chunks), PARALLELING_SIZE)]
    for chunks in tqdm(chunk_of_chunks):
        tasks = [
            compute_churches_llm_name_by_batch(
                chunk, prompt_template, client
            ) for chunk in chunks
        ]
        await asyncio.gather(*tasks)


def compute_churches_llm_name(prompt_template: str | None = None, max_churches: int = 100) -> None:
    # print(json.dumps(LLMOutput.model_json_schema(), indent=2))
    # return

    if prompt_template is None:
        prompt_template = get_prompt_template_for_name()

    prompt_template_hash = hash_string_to_hex(prompt_template)
    already_computed_churches_uuids = Church.objects.filter(
        llm_names__prompt_template_hash=prompt_template_hash
    ).values_list('uuid', flat=True)

    if len(already_computed_churches_uuids) >= max_churches:
        print(f'Skipping computation for {len(already_computed_churches_uuids)} churches,'
              f' already computed.')
        return

    not_computed_churches = Church.objects.exclude(
        llm_names__prompt_template_hash=prompt_template_hash
    ).distinct()[:max_churches - len(already_computed_churches_uuids)]
    print(f'will compute {len(not_computed_churches)} churches')

    load_dotenv()
    openai_api_key = os.getenv("OPENAI_API_KEY")
    client = AsyncOpenAI(api_key=openai_api_key)

    chunks = [not_computed_churches[i:i + BATCH_SIZE]
              for i in range(0, len(not_computed_churches), BATCH_SIZE)]
    run_and_close(compute_in_parallel(chunks, prompt_template, client), client.close)
