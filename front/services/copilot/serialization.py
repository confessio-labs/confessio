"""(De)serialize the PydanticAI message history to/from the JSON stored on
CopilotDiscussion.pydantic_messages."""
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from pydantic_core import to_jsonable_python


def dump_messages(messages: list[ModelMessage]) -> list:
    """Serialize a PydanticAI message history to a JSON-able list for the JSONField."""
    return to_jsonable_python(messages)


def load_messages(raw: list | None) -> list[ModelMessage]:
    """Rebuild a PydanticAI message history from the stored JSON (empty list if none)."""
    if not raw:
        return []
    return ModelMessagesTypeAdapter.validate_python(raw)
