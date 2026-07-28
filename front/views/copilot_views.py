from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from front.models import CopilotDiscussion, CopilotDiscussionItem
from front.services.copilot.items import add_item
from front.tasks import worker_resume_copilot_turn, worker_run_copilot_turn

Status = CopilotDiscussion.Status
ItemType = CopilotDiscussionItem.ItemType
ApprovalStatus = CopilotDiscussionItem.ApprovalStatus

# Statuses from which a new human message may claim the next turn. Everything except RUNNING: an
# ERROR discussion is recoverable by talking to it again, and AWAITING_APPROVAL is superseded (see
# _refuse_pending_proposals).
_CLAIMABLE_STATUSES = (Status.IDLE, Status.AWAITING_APPROVAL, Status.ERROR)


def _discussions_for(user):
    return CopilotDiscussion.objects.filter(user=user).order_by('-updated_at')


def _refuse_pending_proposals(discussion) -> list[dict]:
    """A new human message supersedes any action still awaiting approval: mark them refused.

    This gives their tool calls a result in the history rebuilt for the next turn — an unanswered
    tool call followed by a user prompt is rejected by the provider — and stops the UI offering
    Valider/Refuser on an action the admin has already moved past. Returns the re-rendered cards so
    the caller can refresh them client-side (polling only ever returns *new* items).
    """
    refused = []
    for item in discussion.items.filter(item_type=ItemType.PROPOSED_TOOL_CALL,
                                        approval_status=ApprovalStatus.PENDING):
        item.approval_status = ApprovalStatus.REJECTED
        item.save(update_fields=['approval_status', 'updated_at'])
        refused.append({
            'uuid': str(item.uuid),
            'html': render_to_string('partials/copilot_items.html', {'items': [item]}),
        })
    return refused


@login_required
@permission_required("scheduling.change_sentence")
def copilot(request, discussion_uuid=None):
    discussion = None
    items = []
    if discussion_uuid is not None:
        discussion = get_object_or_404(CopilotDiscussion, uuid=discussion_uuid, user=request.user)
        items = list(discussion.items.all())
    return render(request, 'pages/copilot.html', {
        'discussions': _discussions_for(request.user),
        'discussion': discussion,
        'items': items,
    })


@login_required
@permission_required("scheduling.change_sentence")
@require_POST
def copilot_new(request):
    text = (request.POST.get('text') or '').strip()
    if not text:
        return JsonResponse({'error': 'empty'}, status=400)
    discussion = CopilotDiscussion.objects.create(
        user=request.user, title=text[:80], status=Status.RUNNING)
    add_item(discussion, ItemType.USER_MESSAGE, text=text)
    worker_run_copilot_turn(str(discussion.uuid), text)
    return JsonResponse({'redirect': reverse('copilot_view', args=[discussion.uuid])})


@login_required
@permission_required("scheduling.change_sentence")
@require_POST
def copilot_message(request, discussion_uuid):
    discussion = get_object_or_404(CopilotDiscussion, uuid=discussion_uuid, user=request.user)
    text = (request.POST.get('text') or '').strip()
    if not text:
        return JsonResponse({'error': 'empty'}, status=400)
    # Claim the turn with a conditional update: only a run already in flight is refused, and the
    # compare-and-set closes the race with a concurrent approval, which flips the same way.
    claimed = CopilotDiscussion.objects.filter(
        uuid=discussion.uuid, status__in=_CLAIMABLE_STATUSES).update(
            status=Status.RUNNING, error_message='')
    if not claimed:
        return JsonResponse({'error': 'busy'}, status=409)
    refused = _refuse_pending_proposals(discussion)
    add_item(discussion, ItemType.USER_MESSAGE, text=text)
    worker_run_copilot_turn(str(discussion.uuid), text)
    return JsonResponse({'ok': True, 'refused': refused})


@login_required
@permission_required("scheduling.change_sentence")
@require_POST
def copilot_approve(request, discussion_uuid):
    discussion = get_object_or_404(CopilotDiscussion, uuid=discussion_uuid, user=request.user)
    item = get_object_or_404(
        CopilotDiscussionItem, uuid=request.POST.get('item_uuid'), discussion=discussion,
        item_type=ItemType.PROPOSED_TOOL_CALL)
    if item.approval_status != ApprovalStatus.PENDING:
        return JsonResponse({'error': 'already_resolved'}, status=409)
    approved = request.POST.get('decision') == 'approve'
    item.approval_status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    item.save(update_fields=['approval_status', 'updated_at'])

    # The agent can propose several tools at once; PydanticAI requires results for ALL of them on
    # resume. So only resume once every proposed tool call in the batch has been decided. The
    # status flip is conditional (AWAITING_APPROVAL -> RUNNING) so concurrent decisions can't
    # trigger the resume twice.
    still_pending = discussion.items.filter(
        item_type=ItemType.PROPOSED_TOOL_CALL, approval_status=ApprovalStatus.PENDING).exists()
    if not still_pending:
        flipped = CopilotDiscussion.objects.filter(
            uuid=discussion.uuid, status=Status.AWAITING_APPROVAL).update(status=Status.RUNNING)
        if flipped:
            worker_resume_copilot_turn(str(discussion.uuid))

    item_html = render_to_string('partials/copilot_items.html', {'items': [item]})
    return JsonResponse({'ok': True, 'pending': still_pending, 'item_html': item_html})


@login_required
@permission_required("scheduling.change_sentence")
def copilot_items(request, discussion_uuid):
    discussion = get_object_or_404(CopilotDiscussion, uuid=discussion_uuid, user=request.user)
    try:
        since = int(request.GET.get('since', -1))
    except (TypeError, ValueError):
        since = -1
    new_items = discussion.items.filter(position__gt=since)
    html = render_to_string('partials/copilot_items.html', {'items': new_items})
    last = new_items.last()
    return JsonResponse({
        'status': discussion.status,
        'error_message': discussion.error_message,
        'html': html,
        'last_position': last.position if last else since,
    })
