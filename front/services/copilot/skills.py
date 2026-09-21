"""The copilot's skills: detailed procedures kept OUT of the base system prompt.

Each skill is a pydantic-ai `Capability(defer_loading=True)`: the model only sees its id and its
description on every turn, and pulls the full instructions with the framework's `load_capability`
tool when a discussion actually calls for them. Adding a skill = adding a Capability to SKILLS.

Skills carry instructions only, never tools: a tool owned by a deferred capability would be
missing from the run that resumes after an admin approval (runner.resume_after_approval), where
the capability starts unloaded again.
"""
from pydantic_ai.capabilities import Capability

from front.services.copilot.deps import CopilotDeps

FIX_PARSING_SCHEDULES_ID = 'fix_parsing_schedules'

_FIX_PARSING_SCHEDULES = """\
Corriger les HORAIRES d'un parsing (app scheduling).

Les horaires extraits d'une page vivent dans un Parsing : `llm_json` (sortie du LLM de parsing) \
et `human_json` (validé par un humain, qui prime sur `llm_json`).

Enquêter :
- Enchaînement : identifie le Website (et propose `assign_website`), puis `get_website_parsings` \
pour lister ses parsings, puis `get_parsing` pour lire l'extrait HTML source et les églises. \
N'utilise pas `run_sql` pour ça : il tronque les cellules à 2000 caractères, donc le HTML \
reviendrait coupé.

QUAND corriger :
- Ne modifie un parsing QUE si le LLM de parsing s'est effectivement trompé, c'est-à-dire si sa \
sortie contredit l'extrait HTML source, lu à l'aune du prompt reproduit plus bas.
- Ne « corrige » JAMAIS un parsing artificiellement pour faire enregistrer des horaires de \
force. Si l'horaire annoncé par l'admin n'est pas dans l'extrait HTML, la panne est ailleurs \
(page pas crawlée, pruning trop agressif, mauvais rattachement d'église) : explique-le à l'admin \
ou ouvre un `report_bug`, ne le compense pas dans `human_json`.
- Si le LLM a correctement appliqué son prompt et que c'est le prompt qui est insuffisant, c'est \
aussi un `report_bug`, pas une correction manuelle.

COMMENT corriger, une fois l'erreur du LLM établie :
- `update_parsing_human_json` REMPLACE toute la liste d'horaires : renvoie aussi les horaires \
corrects déjà présents, sinon ils seront perdus.
- `church_id` doit être une clé de `church_desc_by_id` du parsing ; `-1` = une autre église, \
`null` = église non précisée dans le texte.
- Après validation, tout le pipeline (prune → parse → match → index) est relancé pour les sites \
concernés : ne le propose que si le contenu change vraiment.\
"""


def _parsing_prompt_instructions() -> str:
    # Resolved only when the model loads the skill: the template is ~7 400 characters, and
    # parse_with_llm pulls dateutil + holidays + httpx, which have nothing to do on the web
    # startup path.
    from scheduling.public_workflow import scheduling_get_parsing_prompt_template

    return """\
Prompt exact soumis au LLM de parsing. `{truncated_html}` y est remplacé par l'extrait HTML du \
parsing et `{church_description}` par ses églises. C'est à l'aune de ces consignes que tu juges \
si le LLM s'est trompé :

""" + scheduling_get_parsing_prompt_template()


fix_parsing_schedules = Capability[CopilotDeps](
    id=FIX_PARSING_SCHEDULES_ID,
    description="Corriger les horaires d'un parsing (app scheduling) : quand le faire, comment, "
                "et le prompt exact soumis au LLM de parsing.",
    instructions=[_FIX_PARSING_SCHEDULES, _parsing_prompt_instructions],
    defer_loading=True,
)

SKILLS = [fix_parsing_schedules]
