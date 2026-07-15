"""(De)serialize the PydanticAI message history to/from the JSON stored on
CopilotDiscussion.pydantic_messages."""
from pydantic_ai.messages import (ModelMessage, ModelMessagesTypeAdapter, ModelResponse,
                                  RetryPromptPart, ToolCallPart, ToolReturnPart, UserPromptPart)
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


def latest_user_prompt(messages: list[ModelMessage]) -> str | None:
    """Content of the most recent user prompt in the history (None if there is none).

    Used to make a turn re-run idempotent: if the preserved history already ends with this exact
    prompt, the turn was partially run before (auto-retry / dead-task requeue), so we resume with
    user_prompt=None instead of appending a duplicate user message.
    """
    for message in reversed(messages):
        for part in message.parts:
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                return part.content
    return None


def is_resumable_history(messages: list[ModelMessage]) -> bool:
    """Whether a (possibly partial) history can be resumed by a later agent run.

    A crash during a model request leaves the history ending in a ModelRequest (user prompt or tool
    returns) with no following ModelResponse — resumable. A crash *during tool execution* leaves a
    trailing ModelResponse with unanswered tool calls, which PydanticAI refuses to resume — not
    resumable, so we must not overwrite the last clean history with it.
    """
    if not messages:
        return True
    last = messages[-1]
    if isinstance(last, ModelResponse):
        return not any(isinstance(part, ToolCallPart) for part in last.parts)
    return True


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
