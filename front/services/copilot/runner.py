"""Runs one copilot turn (or resumes after an approval) and materializes the result into
CopilotDiscussionItem rows. Executed from the django-background-tasks worker (front/tasks.py).

Autonomous tool calls are recorded by the tools themselves as they run (incremental UI). Here we
add the agent's final text message and any PROPOSED_TOOL_CALL items, then persist the PydanticAI
message history (the agent's source of truth) and update the discussion status.
"""
from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.tools import ToolDenied

from core.utils.async_utils import run_and_close
from front.models import CopilotDiscussion, CopilotDiscussionItem
from front.services.copilot.agent import CopilotDeps, agent, build_provider_and_model
from front.services.copilot.items import add_item
from front.services.copilot.serialization import dump_messages, load_messages

Status = CopilotDiscussion.Status
ItemType = CopilotDiscussionItem.ItemType
ApprovalStatus = CopilotDiscussionItem.ApprovalStatus


def run_agent_turn(discussion_uuid: str, user_text: str) -> None:
    _execute(discussion_uuid, user_prompt=user_text)


def resume_after_approval(discussion_uuid: str, tool_call_id: str, approved: bool) -> None:
    if approved:
        results = DeferredToolResults(approvals={tool_call_id: True})
    else:
        results = DeferredToolResults(approvals={
            tool_call_id: ToolDenied(message="L'admin a refusé cette action.")})
    _execute(discussion_uuid, user_prompt=None, deferred_tool_results=results)


def _execute(discussion_uuid, user_prompt, deferred_tool_results=None) -> None:
    discussion = CopilotDiscussion.objects.get(uuid=discussion_uuid)
    CopilotDiscussion.objects.filter(uuid=discussion_uuid).update(
        status=Status.RUNNING, error_message='')

    try:
        provider, model = build_provider_and_model()  # raises if key missing
        history = load_messages(discussion.pydantic_messages)
        deps = CopilotDeps(discussion_uuid=str(discussion_uuid))

        async def _coro():
            return await agent.run(
                user_prompt,
                message_history=history,
                deferred_tool_results=deferred_tool_results,
                deps=deps,
                model=model,
            )

        result = run_and_close(_coro(), provider.client.close)
    except Exception as e:  # noqa: BLE001
        CopilotDiscussion.objects.filter(uuid=discussion_uuid).update(
            status=Status.ERROR, error_message=f'{type(e).__name__}: {e}')
        raise

    _finalize(discussion, result)


def _finalize(discussion: CopilotDiscussion, result) -> None:
    # 1. The agent's final user-facing text (the last model response).
    agent_text = _last_text(result.new_messages())
    if agent_text:
        add_item(discussion, ItemType.AGENT_MESSAGE, text=agent_text)

    # 2. Any tool calls awaiting approval become PROPOSED_TOOL_CALL items.
    output = result.output
    if isinstance(output, DeferredToolRequests):
        for call in output.approvals:
            add_item(
                discussion,
                ItemType.PROPOSED_TOOL_CALL,
                tool_name=call.tool_name,
                tool_args=_safe_args(call),
                tool_call_id=call.tool_call_id,
                approval_status=ApprovalStatus.PENDING,
            )
        new_status = Status.AWAITING_APPROVAL
    else:
        new_status = Status.IDLE

    # 3. Persist the agent's message history + status.
    CopilotDiscussion.objects.filter(uuid=discussion.uuid).update(
        status=new_status,
        pydantic_messages=dump_messages(result.all_messages()),
    )


def _last_text(messages) -> str:
    for message in reversed(messages):
        if isinstance(message, ModelResponse):
            texts = [p.content for p in message.parts
                     if isinstance(p, TextPart) and p.content.strip()]
            if texts:
                return '\n\n'.join(texts)
            return ''
    return ''


def _safe_args(call) -> dict:
    try:
        return call.args_as_dict()
    except Exception:  # noqa: BLE001
        return {'raw': call.args_as_json_str()}
