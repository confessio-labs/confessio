from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from front.models import Conversation
from front.services.messaging.messaging_service import send_message

# The sidebar has neither scrolling nor pagination: cap the list to the most recent ones.
_MAX_CONVERSATIONS = 50


def _conversations():
    return Conversation.objects.order_by('-updated_at')[:_MAX_CONVERSATIONS]


@login_required
@permission_required("scheduling.change_sentence")
def messaging(request, conversation_uuid=None):
    conversation = None
    messages = []
    if conversation_uuid is not None:
        conversation = get_object_or_404(Conversation, uuid=conversation_uuid)
        messages = list(conversation.messages.all())
    return render(request, 'pages/messaging.html', {
        'conversations': _conversations(),
        'conversation': conversation,
        'messages': messages,
    })


@login_required
@permission_required("scheduling.change_sentence")
@require_POST
def messaging_new(request):
    email = (request.POST.get('email') or '').strip()
    subject = (request.POST.get('subject') or '').strip()
    text = (request.POST.get('text') or '').strip()
    if not email or not subject or not text:
        return HttpResponseBadRequest("Missing required fields")

    # The conversation and its first message are created together: no empty threads.
    conversation = Conversation.objects.create(email=email, subject=subject)
    send_message(request, conversation, text, request.user)
    return redirect('messaging_view', conversation_uuid=conversation.uuid)


@login_required
@permission_required("scheduling.change_sentence")
@require_POST
def messaging_message(request, conversation_uuid):
    conversation = get_object_or_404(Conversation, uuid=conversation_uuid)
    text = (request.POST.get('text') or '').strip()
    if not text:
        return HttpResponseBadRequest("Missing required fields")

    send_message(request, conversation, text, request.user)
    return redirect('messaging_view', conversation_uuid=conversation.uuid)
