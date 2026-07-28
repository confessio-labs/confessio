"""(De)serialize the PydanticAI message history to/from the JSON stored on
CopilotDiscussion.pydantic_messages."""
from pydantic_ai.messages import (ModelMessage, ModelMessagesTypeAdapter, ModelRequest,
                                  ModelResponse, RetryPromptPart, TextPart, ToolCallPart,
                                  ToolReturnPart, UserPromptPart)
from pydantic_core import to_jsonable_python

from crawling.utils.string_utils import strip_null_bytes

# Denial text put into a ToolReturnPart when reconstructing a rejected proposed tool call; the
# runner's resume path uses the same constant for ToolDenied so the two stay in sync.
TOOL_DENIED_MESSAGE = "L'admin a refusé cette action."

# Fallback text for a proposed tool call that never got a result yet is no longer the trailing one
# (see _trailing_unresolved_start): its outcome is genuinely unknown, but the call must be answered.
TOOL_UNRESOLVED_MESSAGE = "Cette action n'a pas abouti : aucun résultat n'a été enregistré."


def dump_messages(messages: list[ModelMessage]) -> list:
    """Serialize a PydanticAI message history to a JSON-able list for the JSONField.

    Null bytes (which Postgres jsonb rejects) are stripped: tool-call args and tool return
    values embedded in the history can carry NUL from model output, fetched pages, or DB cells.
    """
    return strip_null_bytes(to_jsonable_python(messages))


def load_messages(raw: list | None) -> list[ModelMessage]:
    """Rebuild a PydanticAI message history from the stored JSON (empty list if none)."""
    if not raw:
        return []
    return ModelMessagesTypeAdapter.validate_python(raw)


def _synth_tool_call_id(position: int) -> str:
    """Deterministic, non-empty tool_call_id for autonomous items (which store none).

    Position is unique per discussion, and the prefix cannot collide with pydantic-ai's `pyd_ai_*`
    or a provider's `call_*` ids, so a call and its return stay correctly paired.
    """
    return f'auton_{position}'


def _tool_call_response(item: dict, call_id: str) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(
        tool_name=item['tool_name'], args=item['tool_args'], tool_call_id=call_id)])


def _tool_return_request(item: dict, call_id: str, content) -> ModelRequest:
    return ModelRequest(parts=[ToolReturnPart(
        tool_name=item['tool_name'], content=content, tool_call_id=call_id)])


def _is_unresolved_proposal(item: dict) -> bool:
    """A proposed tool call with no result and no explicit refusal — nothing answers it yet."""
    return (item['item_type'] == 'proposed_tool_call'
            and item['tool_result'] is None
            and item['approval_status'] != 'rejected')


def _trailing_unresolved_start(items: list[dict]) -> int:
    """Index where the trailing run of still-unanswered proposed calls begins.

    Only that trailing batch may stay deferred — it is exactly what the resume path answers with
    DeferredToolResults. An unanswered tool call with any item after it makes the whole history
    invalid for the provider ("an assistant message with 'tool_calls' must be followed by tool
    messages responding to each tool_call_id"), so everything before the trailing run is answered.
    """
    index = len(items)
    while index > 0 and _is_unresolved_proposal(items[index - 1]):
        index -= 1
    return index


def build_history_from_item_dicts(items: list[dict]) -> list[ModelMessage]:
    """Rebuild the agent's message history from ordered CopilotDiscussionItem values.

    The items are the durable, complete record (user messages, autonomous tool calls with their
    results, agent messages, proposed tool calls with their approval outcome), so this reconstructs
    the full context even when `pydantic_messages` lost a turn to a crash. Each item maps to one
    ModelResponse/ModelRequest pair; PydanticAI's own `_clean_message_history` then merges them into
    the native grouped shape. Item dicts carry the raw CopilotDiscussionItem.ItemType /
    ApprovalStatus string values. Whether a proposed call is answered or left deferred is driven by
    the presence of `tool_result` and by position, not by `approval_status` alone: only the trailing
    run of unresolved calls may stay unanswered (see _trailing_unresolved_start).
    """
    messages: list[ModelMessage] = []
    deferred_from = _trailing_unresolved_start(items)
    for index, item in enumerate(items):
        item_type = item['item_type']
        if item_type == 'user_message':
            messages.append(ModelRequest(parts=[UserPromptPart(content=item['text'])]))
        elif item_type == 'agent_message':
            messages.append(ModelResponse(parts=[TextPart(content=item['text'])]))
        elif item_type == 'autonomous_tool_call':
            call_id = _synth_tool_call_id(item['position'])
            messages.append(_tool_call_response(item, call_id))
            messages.append(_tool_return_request(item, call_id, item['tool_result']))
        elif item_type == 'proposed_tool_call':
            call_id = item['tool_call_id'] or _synth_tool_call_id(item['position'])
            messages.append(_tool_call_response(item, call_id))
            if item['tool_result'] is not None:
                # approved+executed, or a failure carrying its error dict → answered
                messages.append(_tool_return_request(item, call_id, item['tool_result']))
            elif item['approval_status'] == 'rejected':
                messages.append(_tool_return_request(item, call_id, TOOL_DENIED_MESSAGE))
            elif index < deferred_from:
                # Unresolved, but a later item followed it (a new human message superseded it, or
                # the result was never written): answer it, or the whole history is rejected.
                messages.append(_tool_return_request(item, call_id, TOOL_UNRESOLVED_MESSAGE))
            # else: trailing pending batch → leave unanswered (answered on the resume path)
    return messages


def deferred_tool_call_ids(messages: list[ModelMessage]) -> set[str]:
    """Tool calls in the history that have no result yet (still awaiting approval/execution).

    A proposed (approval-required) tool call stays deferred until its result lands in the history
    (a ToolReturnPart once executed/denied, or a RetryPromptPart). When the agent proposes several
    in one turn, PydanticAI requires results for ALL of them at once on resume, so the caller must
    gather every decision before resuming.
    """
    called: set[str] = set()
    resolved: set[str] = set()
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                called.add(part.tool_call_id)
            elif isinstance(part, (ToolReturnPart, RetryPromptPart)):
                resolved.add(part.tool_call_id)
    return called - resolved
