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
from crawling.utils.string_utils import remove_unsafe_chars
from front.models import CopilotDiscussion, CopilotDiscussionItem
from front.services.copilot.agent import CopilotDeps, agent, build_provider_and_model
from front.services.copilot.items import add_item
from front.services.copilot.serialization import (deferred_tool_call_ids, dump_messages,
                                                  is_resumable_history, latest_user_prompt,
                                                  load_messages)

Status = CopilotDiscussion.Status
ItemType = CopilotDiscussionItem.ItemType
ApprovalStatus = CopilotDiscussionItem.ApprovalStatus


def run_agent_turn(discussion_uuid: str, user_text: str) -> None:
    # Idempotency: if a previous attempt of this same turn already ran partially (auto-retry after a
    # transient error, or a dead-task requeue), its history was preserved and already ends with this
    # prompt — resume it instead of appending a duplicate user message.
    discussion = CopilotDiscussion.objects.get(uuid=discussion_uuid)
    if latest_user_prompt(load_messages(discussion.pydantic_messages)) == user_text:
        _execute(discussion_uuid, user_prompt=None)
    else:
        _execute(discussion_uuid, user_prompt=user_text)


def resume_after_approval(discussion_uuid: str) -> None:
    """Resume the run now that every proposed tool call in the pending batch has been decided.

    PydanticAI requires results for ALL deferred tool calls at once, so we gather each decision
    from the items (approved → execute, anything else → deny) and resume a single time.
    """
    discussion = CopilotDiscussion.objects.get(uuid=discussion_uuid)
    deferred_ids = deferred_tool_call_ids(load_messages(discussion.pydantic_messages))
    decisions = {
        item.tool_call_id: item.approval_status
        for item in discussion.items.filter(
            item_type=ItemType.PROPOSED_TOOL_CALL, tool_call_id__in=deferred_ids)
    }
    denied = ToolDenied(message="L'admin a refusé cette action.")
    approvals = {
        call_id: (True if decisions.get(call_id) == ApprovalStatus.APPROVED else denied)
        for call_id in deferred_ids
    }
    _execute(discussion_uuid, user_prompt=None,
             deferred_tool_results=DeferredToolResults(approvals=approvals))


def _execute(discussion_uuid, user_prompt, deferred_tool_results=None) -> None:
    discussion = CopilotDiscussion.objects.get(uuid=discussion_uuid)
    CopilotDiscussion.objects.filter(uuid=discussion_uuid).update(
        status=Status.RUNNING, error_message='')

    # Captured from inside the run so that, if the turn crashes mid-way (e.g. a transient OpenAI
    # connection/timeout error after several tool calls), we can still persist the partial message
    # history instead of losing the whole turn's memory.
    capture = {'messages': None}
    try:
        provider, model = build_provider_and_model()  # raises if key missing
        history = load_messages(discussion.pydantic_messages)
        deps = CopilotDeps(discussion_uuid=str(discussion_uuid))

        async def _coro():
            async with agent.iter(
                user_prompt,
                message_history=history,
                deferred_tool_results=deferred_tool_results,
                deps=deps,
                model=model,
            ) as run:
                try:
                    async for _node in run:
                        pass
                finally:
                    # all_messages() is the live history; capture it on success AND on failure.
                    capture['messages'] = run.all_messages()
                return run.result

        result = run_and_close(_coro(), provider.client.close)
    except Exception as e:  # noqa: BLE001
        _persist_failure(discussion_uuid, capture['messages'], e)
        raise  # re-raise so the task retries; run_agent_turn then resumes (no duplicate work)

    _finalize(discussion, result)


def _persist_failure(discussion_uuid, messages, exc) -> None:
    """Record the failure on the discussion, preserving the partial (resumable) message history.

    The partial-history persist is guarded by its own try/except so a serialization/DB problem there
    can never mask the original error. A non-resumable partial history (trailing unanswered tool
    calls) is dropped, keeping the last clean pydantic_messages so a later resume stays valid.
    """
    fields = {
        'status': Status.ERROR,
        'error_message': remove_unsafe_chars(f'{type(exc).__name__}: {exc}'),
    }
    try:
        if messages and is_resumable_history(messages):
            fields['pydantic_messages'] = dump_messages(messages)
    except Exception:  # noqa: BLE001
        pass
    CopilotDiscussion.objects.filter(uuid=discussion_uuid).update(**fields)


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
