from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Prefetch
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from front.models import Conversation, MessageImage
from front.services.messaging.messaging_service import read_image_attachments, send_message
from front.utils.messaging_utils import find_error_in_outbound_images

# The sidebar has neither scrolling nor pagination: cap the list to the most recent ones.
_MAX_CONVERSATIONS = 50


def _conversations():
    return Conversation.objects.order_by('-updated_at')[:_MAX_CONVERSATIONS]


@login_required
@permission_required("scheduling.change_sentence")
def messaging(request, conversation_uuid=None):
    conversation = None
    messages = []
    moderation = None
    if conversation_uuid is not None:
        conversation = get_object_or_404(Conversation, uuid=conversation_uuid)
        messages = list(conversation.messages.prefetch_related(
            Prefetch('images', queryset=MessageImage.objects.defer('content'))))
        # At most one, since ConversationModeration has a single category. A thread we opened
        # ourselves from here has none until the correspondent answers.
        moderation = conversation.moderations.first()
    return render(request, 'pages/messaging.html', {
        'conversations': _conversations(),
        'conversation': conversation,
        'messages': messages,
        'moderation': moderation,
    })


@login_required
@permission_required("scheduling.change_sentence")
@require_POST
def messaging_new(request):
    email = (request.POST.get('email') or '').strip()
    subject = (request.POST.get('subject') or '').strip()
    text = (request.POST.get('text') or '').strip()
    images = read_image_attachments(request.FILES.getlist('images'))
    if not email or not subject or not (text or images):
        return HttpResponseBadRequest("Missing required fields")
    error = find_error_in_outbound_images(images)
    if error:
        return HttpResponseBadRequest(error)

    # The conversation and its first message are created together: no empty threads.
    conversation = Conversation.objects.create(email=email, subject=subject)
    send_message(request, conversation, text, request.user, images)
    return redirect('messaging_view', conversation_uuid=conversation.uuid)


@login_required
@permission_required("scheduling.change_sentence")
@require_POST
def messaging_message(request, conversation_uuid):
    conversation = get_object_or_404(Conversation, uuid=conversation_uuid)
    text = (request.POST.get('text') or '').strip()
    images = read_image_attachments(request.FILES.getlist('images'))
    if not (text or images):
        return HttpResponseBadRequest("Missing required fields")
    error = find_error_in_outbound_images(images)
    if error:
        return HttpResponseBadRequest(error)

    send_message(request, conversation, text, request.user, images)
    return redirect('messaging_view', conversation_uuid=conversation.uuid)


@login_required
@permission_required("scheduling.change_sentence")
def messaging_image(request, image_uuid):
    image = get_object_or_404(MessageImage, uuid=image_uuid)
    response = HttpResponse(bytes(image.content), content_type=image.content_type)
    # Never public: this is private correspondence. An image never changes once stored.
    response['Cache-Control'] = 'private, max-age=31536000, immutable'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
