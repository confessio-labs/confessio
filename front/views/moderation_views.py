from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render

from core.views import get_moderate_response
from front.models import ApprovalModeration, ConversationModeration, IssueModeration, Message
from front.services.moderation_stats_service import get_moderation_stats


@login_required
@permission_required("scheduling.change_sentence")
def moderation_home(request):
    my_stats, other_stats = get_moderation_stats(request.user)
    return render(request, 'pages/moderation_home.html', {
        'my_stats': my_stats,
        'other_stats': other_stats,
    })


@login_required
@permission_required("scheduling.change_sentence")
def moderate_issue(request, category, status, moderation_uuid=None):
    return get_moderate_response(request, category, 'issue', status,
                                 IssueModeration, moderation_uuid,
                                 create_issue_moderation_context)


def create_issue_moderation_context(moderation: IssueModeration) -> dict:
    return {
        'issue': moderation.issue,
        'comments': moderation.issue.comments.order_by('created_at'),
    }


@login_required
@permission_required("scheduling.change_sentence")
def moderate_approval(request, category, status, moderation_uuid=None):
    return get_moderate_response(request, category, 'approval', status,
                                 ApprovalModeration, moderation_uuid,
                                 create_approval_moderation_context)


def create_approval_moderation_context(moderation: ApprovalModeration) -> dict:
    return {
        'approval': moderation.approval,
        'comments': moderation.approval.comments.order_by('created_at'),
    }


@login_required
@permission_required("scheduling.change_sentence")
def moderate_conversation(request, category, status, moderation_uuid=None):
    return get_moderate_response(request, category, 'conversation', status,
                                 ConversationModeration, moderation_uuid,
                                 create_conversation_moderation_context)


def create_conversation_moderation_context(moderation: ConversationModeration) -> dict:
    conversation = moderation.conversation
    # Message.Meta orders by created_at, so last() is the latest one received.
    last_message = conversation.messages.filter(direction=Message.Direction.INBOUND).last()

    return {
        'conversation': conversation,
        'last_message': last_message,
    }
