"""The admin copilot PydanticAI agent: model factory, system prompt, and the tool set.

Autonomous tools (read-only SQL, visit URL, Google / Google Maps) execute inline and record an
AUTONOMOUS_TOOL_CALL item as they run. Proposed tools (registry CRUD, recrawl, assign website,
report bug) are `requires_approval=True`: on the first turn they surface as DeferredToolRequests
and the runner records a PROPOSED_TOOL_CALL item; their body only runs after the admin approves.
"""
import os
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from pydantic_ai import Agent, DeferredToolRequests, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from front.models import CopilotDiscussion
from front.services.copilot import tools
from front.services.copilot.items import add_autonomous_tool_item, record_proposed_execution
from front.services.copilot.schema_introspection import describe_table, get_schema_text

COPILOT_MODEL = 'gpt-5'


@dataclass
class CopilotDeps:
    discussion_uuid: str


SYSTEM_PROMPT = """\
Tu es le copilote d'administration de Confessio, un service qui agrège et publie les horaires \
de confession des paroisses catholiques en France.

Un admin te signale un problème « divers et varié » : une paroisse / église erronée, un horaire \
faux ou manquant, un site qui ne se met plus à jour, etc. Tu raisonnes en français.

Architecture Confessio (pour classer le problème) :
- registry : entités ecclésiales (Diocese, Parish, Church géolocalisée, Website d'une paroisse).
- crawling : téléchargement des pages des sites de paroisses (Scraping, logs de crawl).
- scheduling : pipeline qui extrait les horaires depuis les pages (built → pruned → parsed → \
matched → indexed).

Tes objectifs, dans l'ordre :
1. IDENTIFIER le problème : retrouve la paroisse concernée (son Website) et classe le souci \
(registry / crawling / scheduling). Sers-toi des tools pour enquêter (SQL en lecture seule, \
visite du site de la paroisse, recherche Google / Google Maps).
2. DEMANDER DES PRÉCISIONS à l'admin si l'information manque pour conclure.
3. Si c'est un BUG qui demande l'intervention d'un développeur (logique de code, pipeline cassé) \
→ utilise `report_bug` avec un rapport détaillé (symptôme, paroisse/website concerné, étape du \
pipeline, ce que tu as observé, hypothèse de cause).
4. Si des ACTIONS permettent de régler la situation (corriger le registry puis relancer un crawl) \
→ PROPOSE ces actions via les tools dédiés ; l'admin les validera dans l'interface. Explique \
brièvement pourquoi avant de proposer.
5. Si CE N'EST PAS un bug et qu'aucune action n'est nécessaire (l'utilisateur final s'est trompé, \
l'info existe déjà, etc.) → rédige une réponse de type e-mail à destination de l'utilisateur final \
qui a posé la question, en commençant impérativement par : \
« Voici ce que tu peux répondre à l'utilisateur : ».

Règles :
- Le SQL est STRICTEMENT en lecture seule (SELECT/WITH). Le schéma de la base t'est fourni \
ci-dessous ; utilise les vrais noms de tables/colonnes. Les clés primaires sont des UUID.
- Quand tu as identifié le Website concerné, propose `assign_website` pour le rattacher à la \
discussion.
- Les requêtes HTTP (visite de site) peuvent échouer (timeout, 4xx, 5xx) : adapte-toi, n'insiste \
pas inutilement.
- Sois concis et concret. Ne propose une action de modification qu'avec des valeurs précises.\
"""


agent = Agent(
    deps_type=CopilotDeps,
    output_type=[str, DeferredToolRequests],
    instructions=SYSTEM_PROMPT,
)


@agent.instructions
def _schema_instructions(ctx: RunContext[CopilotDeps]) -> str:
    return 'Schéma de la base de données (table(colonne type [-> fk] [flags], ...)) :\n' \
        + get_schema_text()


def build_provider_and_model() -> tuple[OpenAIProvider, OpenAIChatModel]:
    """Build the OpenAI provider + model. The provider is returned too so the caller can close
    its AsyncOpenAI client in the same event loop (see core.utils.async_utils.run_and_close)."""
    api_key = os.getenv('OPENAI_API_KEY_COPILOT')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY_COPILOT is not set')
    provider = OpenAIProvider(api_key=api_key)
    return provider, OpenAIChatModel(COPILOT_MODEL, provider=provider)


# --------------------------------------------------------------------------- #
# Autonomous tools                                                             #
# --------------------------------------------------------------------------- #

def _record_autonomous(discussion_uuid: str, tool_name: str, args: dict, logic, *logic_args):
    """Run a read-only logic fn and persist an AUTONOMOUS_TOOL_CALL item (sync)."""
    result = logic(*logic_args)
    discussion = CopilotDiscussion.objects.get(uuid=discussion_uuid)
    add_autonomous_tool_item(discussion, tool_name, args, result)
    return result


@agent.tool
async def run_sql(ctx: RunContext[CopilotDeps], query: str) -> dict:
    """Run a read-only SQL query (SELECT/WITH only) against the Confessio database."""
    return await sync_to_async(_record_autonomous)(
        ctx.deps.discussion_uuid, 'run_sql', {'query': query}, tools.run_readonly_sql, query)


@agent.tool
async def describe_schema(ctx: RunContext[CopilotDeps], table: str | None = None) -> str:
    """List all tables, or the columns of one table (by its db_table name)."""
    if table:
        return describe_table(table)
    return get_schema_text()


@agent.tool
async def visit_url(ctx: RunContext[CopilotDeps], url: str) -> dict:
    """Fetch the text content of a web page (e.g. a parish website or one of its sub-pages)."""
    return await sync_to_async(_record_autonomous)(
        ctx.deps.discussion_uuid, 'visit_url', {'url': url}, tools.fetch_url, url)


@agent.tool
async def google_search(ctx: RunContext[CopilotDeps], query: str) -> dict:
    """Run a Google web search."""
    return await sync_to_async(_record_autonomous)(
        ctx.deps.discussion_uuid, 'google_search', {'query': query}, tools.google_search, query)


@agent.tool
async def google_maps_search(ctx: RunContext[CopilotDeps], query: str) -> dict:
    """Search Google Maps (places) for a name/address."""
    return await sync_to_async(_record_autonomous)(
        ctx.deps.discussion_uuid, 'google_maps_search', {'query': query},
        tools.google_maps_search, query)


# --------------------------------------------------------------------------- #
# Proposed tools (require admin approval in the UI)                            #
# --------------------------------------------------------------------------- #

def _record_proposed(discussion_uuid: str, tool_call_id: str, logic, *logic_args):
    """Run a mutating logic fn (after approval) and store its result on the proposed item."""
    result = logic(*logic_args)
    discussion = CopilotDiscussion.objects.get(uuid=discussion_uuid)
    record_proposed_execution(discussion, tool_call_id, result)
    return result


@agent.tool(requires_approval=True)
async def assign_website(ctx: RunContext[CopilotDeps], website_uuid: str) -> dict:
    """Attach a Website to this discussion (the identified parish)."""
    return await sync_to_async(_record_proposed)(
        ctx.deps.discussion_uuid, ctx.tool_call_id,
        tools.do_assign_website, ctx.deps.discussion_uuid, website_uuid)


@agent.tool(requires_approval=True)
async def add_church(ctx: RunContext[CopilotDeps], parish_uuid: str, name: str,
                     city: str | None = None, zipcode: str | None = None,
                     address: str | None = None, latitude: float | None = None,
                     longitude: float | None = None) -> dict:
    """Create a new church under a parish."""
    return await sync_to_async(_record_proposed)(
        ctx.deps.discussion_uuid, ctx.tool_call_id, tools.do_add_church,
        parish_uuid, name, city, zipcode, address, latitude, longitude)


@agent.tool(requires_approval=True)
async def update_church(ctx: RunContext[CopilotDeps], church_uuid: str, name: str | None = None,
                        city: str | None = None, zipcode: str | None = None,
                        address: str | None = None, latitude: float | None = None,
                        longitude: float | None = None, parish_uuid: str | None = None,
                        is_active: bool | None = None) -> dict:
    """Update fields of an existing church."""
    return await sync_to_async(_record_proposed)(
        ctx.deps.discussion_uuid, ctx.tool_call_id, tools.do_update_church,
        church_uuid, name, city, zipcode, address, latitude, longitude, parish_uuid, is_active)


@agent.tool(requires_approval=True)
async def delete_church(ctx: RunContext[CopilotDeps], church_uuid: str) -> dict:
    """Delete a church."""
    return await sync_to_async(_record_proposed)(
        ctx.deps.discussion_uuid, ctx.tool_call_id, tools.do_delete_church, church_uuid)


@agent.tool(requires_approval=True)
async def add_parish(ctx: RunContext[CopilotDeps], diocese_uuid: str, name: str,
                     website_uuid: str | None = None) -> dict:
    """Create a new parish in a diocese, optionally attached to a website."""
    return await sync_to_async(_record_proposed)(
        ctx.deps.discussion_uuid, ctx.tool_call_id, tools.do_add_parish,
        diocese_uuid, name, website_uuid)


@agent.tool(requires_approval=True)
async def update_parish(ctx: RunContext[CopilotDeps], parish_uuid: str, name: str | None = None,
                        website_uuid: str | None = None, diocese_uuid: str | None = None) -> dict:
    """Update fields of an existing parish."""
    return await sync_to_async(_record_proposed)(
        ctx.deps.discussion_uuid, ctx.tool_call_id, tools.do_update_parish,
        parish_uuid, name, website_uuid, diocese_uuid)


@agent.tool(requires_approval=True)
async def delete_parish(ctx: RunContext[CopilotDeps], parish_uuid: str) -> dict:
    """Delete a parish."""
    return await sync_to_async(_record_proposed)(
        ctx.deps.discussion_uuid, ctx.tool_call_id, tools.do_delete_parish, parish_uuid)


@agent.tool(requires_approval=True)
async def add_website(ctx: RunContext[CopilotDeps], name: str, home_url: str) -> dict:
    """Create a new website."""
    return await sync_to_async(_record_proposed)(
        ctx.deps.discussion_uuid, ctx.tool_call_id, tools.do_add_website, name, home_url)


@agent.tool(requires_approval=True)
async def update_website(ctx: RunContext[CopilotDeps], website_uuid: str, name: str | None = None,
                         home_url: str | None = None, is_active: bool | None = None,
                         enabled_for_crawling: bool | None = None) -> dict:
    """Update fields of an existing website."""
    return await sync_to_async(_record_proposed)(
        ctx.deps.discussion_uuid, ctx.tool_call_id, tools.do_update_website,
        website_uuid, name, home_url, is_active, enabled_for_crawling)


@agent.tool(requires_approval=True)
async def delete_website(ctx: RunContext[CopilotDeps], website_uuid: str) -> dict:
    """Delete a website."""
    return await sync_to_async(_record_proposed)(
        ctx.deps.discussion_uuid, ctx.tool_call_id, tools.do_delete_website, website_uuid)


@agent.tool(requires_approval=True)
async def trigger_recrawl(ctx: RunContext[CopilotDeps], website_uuid: str) -> dict:
    """Enqueue a fresh crawl of a website."""
    return await sync_to_async(_record_proposed)(
        ctx.deps.discussion_uuid, ctx.tool_call_id, tools.do_trigger_recrawl, website_uuid)


@agent.tool(requires_approval=True)
async def report_bug(ctx: RunContext[CopilotDeps], title: str, details: str) -> dict:
    """Report a bug for a developer to fix. For now this only records the report in the chat."""
    return {'reported': True, 'title': title, 'details': details}
