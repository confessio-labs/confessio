"""(De)serialize the PydanticAI message history to/from the JSON stored on
CopilotDiscussion.pydantic_messages."""
from pydantic_ai.messages import (ModelMessage, ModelMessagesTypeAdapter, RetryPromptPart,
                                  ToolCallPart, ToolReturnPart)
from pydantic_core import to_jsonable_python

from crawling.utils.string_utils import strip_null_bytes


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
