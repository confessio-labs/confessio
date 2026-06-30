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

# Statuses for which the front should keep polling for new items.
_ACTIVE_STATUSES = {Status.RUNNING}


def _discussions_for(user):
    return CopilotDiscussion.objects.filter(user=user).order_by('-updated_at')


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
    if discussion.status in _ACTIVE_STATUSES:
        return JsonResponse({'error': 'busy'}, status=409)
    text = (request.POST.get('text') or '').strip()
    if not text:
        return JsonResponse({'error': 'empty'}, status=400)
    add_item(discussion, ItemType.USER_MESSAGE, text=text)
    CopilotDiscussion.objects.filter(uuid=discussion.uuid).update(status=Status.RUNNING)
    worker_run_copilot_turn(str(discussion.uuid), text)
    return JsonResponse({'ok': True})


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
    CopilotDiscussion.objects.filter(uuid=discussion.uuid).update(status=Status.RUNNING)
    worker_resume_copilot_turn(str(discussion.uuid), item.tool_call_id, approved)
    return JsonResponse({'ok': True})


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
