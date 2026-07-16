"""Synchronous helpers to create/update CopilotDiscussionItem rows. Items are the durable, complete
record of a discussion and the source of truth from which the agent's context is rebuilt each new
turn (build_history_from_items); they also drive the UI and the approval state machine."""
from django.db.models import Max

from crawling.utils.string_utils import strip_null_bytes
from front.models import CopilotDiscussion, CopilotDiscussionItem
from front.services.copilot.serialization import build_history_from_item_dicts

_HISTORY_FIELDS = ('position', 'item_type', 'text', 'tool_name', 'tool_args', 'tool_result',
                   'tool_call_id', 'approval_status')


def build_history_from_items(discussion: CopilotDiscussion) -> list:
    """Rebuild the PydanticAI message history for a discussion from its ordered items."""
    items = list(discussion.items.order_by('position').values(*_HISTORY_FIELDS))
    return build_history_from_item_dicts(items)


def _next_position(discussion: CopilotDiscussion) -> int:
    current = discussion.items.aggregate(m=Max('position'))['m']
    return 0 if current is None else current + 1


def add_item(discussion: CopilotDiscussion, item_type: str, **fields) -> CopilotDiscussionItem:
    return CopilotDiscussionItem.objects.create(
        discussion=discussion,
        position=_next_position(discussion),
        item_type=item_type,
        **{key: strip_null_bytes(value) for key, value in fields.items()},
    )


def add_autonomous_tool_item(discussion: CopilotDiscussion, tool_name: str,
                             tool_args: dict, tool_result) -> CopilotDiscussionItem:
    return add_item(
        discussion,
        CopilotDiscussionItem.ItemType.AUTONOMOUS_TOOL_CALL,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_result=tool_result,
    )


def record_proposed_execution(discussion: CopilotDiscussion, tool_call_id: str,
                              tool_result, *, failed: bool = False) -> None:
    """Fill in the result of a proposed tool that just executed after approval.

    If it failed, also flip the item to FAILURE (it was APPROVED).
    """
    fields = {'tool_result': strip_null_bytes(tool_result)}
    if failed:
        fields['approval_status'] = CopilotDiscussionItem.ApprovalStatus.FAILURE
    (discussion.items
     .filter(tool_call_id=tool_call_id,
             item_type=CopilotDiscussionItem.ItemType.PROPOSED_TOOL_CALL)
     .update(**fields))
