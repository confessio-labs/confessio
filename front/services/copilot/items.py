"""Synchronous helpers to create/update CopilotDiscussionItem rows. Items drive the UI and the
approval state machine; the agent's own memory is CopilotDiscussion.pydantic_messages."""
from django.db.models import Max

from front.models import CopilotDiscussion, CopilotDiscussionItem


def _next_position(discussion: CopilotDiscussion) -> int:
    current = discussion.items.aggregate(m=Max('position'))['m']
    return 0 if current is None else current + 1


def add_item(discussion: CopilotDiscussion, item_type: str, **fields) -> CopilotDiscussionItem:
    return CopilotDiscussionItem.objects.create(
        discussion=discussion,
        position=_next_position(discussion),
        item_type=item_type,
        **fields,
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
                              tool_result) -> None:
    """Fill in the result of a proposed tool that just executed after approval."""
    (discussion.items
     .filter(tool_call_id=tool_call_id,
             item_type=CopilotDiscussionItem.ItemType.PROPOSED_TOOL_CALL)
     .update(tool_result=tool_result))
