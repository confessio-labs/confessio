import json
import os

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.utils.translation import gettext
from django.views.decorators.csrf import csrf_exempt

from core.utils.discord_utils import DiscordChanel, send_discord_alert
from front.services.card.scraping_url_service import quote_path, unquote_path
from front.services.messaging.messaging_service import (ingest_received_email, ingest_sent_email,
                                                        record_contact_form)
from front.utils.cloudflare_utils import verify_token
from front.utils.mailgun_utils import StorageUnavailableError, fetch_stored_message, validate_token
from front.utils.messaging_utils import is_same_email
from registry.models import Diocese, Website
from scheduling.models import IndexEvent

# What we record is the admin's send, not the recipient's server accepting it: a mail that never
# gets delivered was still written and belongs in the thread. 'accepted' also fires once per
# message, where 'delivered' fires once per recipient.
SENT_EVENT = 'accepted'


def contact(request, message=None, email=None, name_text=None,
            message_subject=None, message_text=None):
    if request.method == "GET":
        cloudflare_turnstile_site_key = os.environ.get('CLOUDFLARE_TURNSTILE_SITE_KEY', '')
        return render(request, 'pages/contact.html',
                      {'message': message,
                       'name_text': unquote_path(name_text or ''),
                       'email': email or '',
                       'message_subject': unquote_path(message_subject or ''),
                       'message_text': unquote_path(message_text or ''),
                       'meta_title': gettext('contactPageTitle'),
                       'cloudflare_turnstile_site_key': cloudflare_turnstile_site_key
                       })
    else:
        name = request.POST.get('name')
        from_email = request.POST.get('email')
        subject = request.POST.get('subject', '')
        message = request.POST.get('message')

        if not name or not from_email or not subject or not message:
            return HttpResponseBadRequest("Missing required fields")

        cloudflare_token = request.POST.get('cf-turnstile-response')
        if not verify_token(cloudflare_token):
            print(f"Invalid token: {cloudflare_token}")
            name_text = quote_path(name)
            message_subject = quote_path(subject)
            message_text = quote_path(message)
            return redirect("contact_failure", message='failure',
                            name_text=name_text, email=from_email,
                            message_subject=message_subject, message_text=message_text)

        # The submission is stored, notified on Discord and only then mirrored to the contact
        # mailbox, so a mail failure loses nothing: it shows on the message in /messaging. Sending
        # the visitor back to the failure page would only invite a duplicate conversation.
        record_contact_form(request, name, from_email, subject, message)

        return redirect("contact_success", message='success')


def about(request):
    diocese_count = Diocese.objects.count()
    website_count = Website.objects.count()
    confession_places_count = IndexEvent.objects.values('church').distinct().count()

    return render(request, 'pages/about.html', {
        'meta_title': 'Qui sommes-nous ?',
        'diocese_count': diocese_count,
        'website_count': website_count,
        'confession_places_count': confession_places_count,
    })


@csrf_exempt
def contact_mail_received_webhook(request):
    """Mailgun's inbound route for mail addressed to the contact address."""
    if request.method != 'POST':
        return HttpResponse(status=405)

    if not _is_valid_signature(request.POST.get('token', ''),
                               request.POST.get('timestamp', ''),
                               request.POST.get('signature', '')):
        return HttpResponse(status=403)

    if request.POST.get('recipient', '') != os.environ.get('CONTACT_EMAIL'):
        return HttpResponse(status=200)

    from_header = request.POST.get('from', '')
    # The mails we mirror to the contact mailbox come back through this route. They are already in
    # the conversation, and no-reply@ is by construction an address only we send from.
    if is_same_email(from_header, settings.DEFAULT_FROM_EMAIL):
        return HttpResponse(status=200)

    subject = request.POST.get('subject', '')
    body_plain = request.POST.get('body-plain', '')
    stripped_text = request.POST.get('stripped-text', '')
    try:
        ingest_received_email(request,
                              from_header=from_header,
                              reply_to=request.POST.get('Reply-To', ''),
                              subject=subject,
                              body_plain=body_plain,
                              stripped_text=stripped_text,
                              message_id=request.POST.get('Message-Id', ''),
                              in_reply_to=request.POST.get('In-Reply-To', ''),
                              references=request.POST.get('References', ''))
    except Exception as e:
        # Never fail the webhook on an ingestion problem: Mailgun would retry the delivery. Ring
        # Discord with the raw mail instead — the conversation is lost, the message must not be.
        print(e)
        send_discord_alert(
            message=f"Mail entrant non enregistré ({e})\n\n"
                    f"FROM:{from_header}\nSUBJECT:{subject}\n\n{stripped_text or body_plain}",
            channel=DiscordChanel.CONTACT_FORM)

    return HttpResponse(status=200)


@csrf_exempt
def contact_mail_sent_webhook(request):
    """Mailgun's event webhook for mail sent from the contact mailbox, outside /messaging."""
    if request.method != 'POST':
        return HttpResponse(status=405)

    try:
        payload = json.loads(request.body)
        signature = payload['signature']
        event_data = payload['event-data']
    except (ValueError, KeyError, TypeError) as e:
        print(e)
        return HttpResponseBadRequest("Malformed payload")

    if not _is_valid_signature(signature.get('token', ''), signature.get('timestamp', ''),
                               signature.get('signature', '')):
        return HttpResponse(status=403)

    if event_data.get('event') != SENT_EVENT:
        return HttpResponse(status=200)

    # Mailgun raises this event for the mail it routes INTO the contact mailbox as well, so read
    # the sender off the event and stop here unless the mail left that mailbox. The same check
    # guards the ingestion, but downloading a body to then throw it away is what made a contact
    # form submission look like a broken webhook.
    headers = (event_data.get('message') or {}).get('headers') or {}
    if not is_same_email(headers.get('from', ''), os.environ.get('CONTACT_EMAIL', '')):
        return HttpResponse(status=200)

    storage_url = (event_data.get('storage') or {}).get('url', '')
    if not storage_url:
        # Nothing to download from, so nothing to record.
        return HttpResponse(status=200)

    if not os.environ.get('MAILGUN_API_KEY'):
        # A missing key does not fix itself: answering 5xx would have Mailgun retry for hours.
        print("Cannot record a sent mail: MAILGUN_API_KEY is not set")
        return HttpResponse(status=200)

    try:
        stored = fetch_stored_message(storage_url)
    except StorageUnavailableError as e:
        # Only a replay can fix this one, and 5xx is how we ask Mailgun for it. The Message-Id
        # de-dup makes the replay safe.
        print(e)
        return HttpResponse(status=500)

    if stored is None:
        # Nothing a retry could change — Mailgun keeps no message for this domain, or the key was
        # refused. Replaying would just repeat the failure for hours.
        return HttpResponse(status=200)

    try:
        ingest_sent_email(stored)
    except Exception as e:
        print(e)

    return HttpResponse(status=200)


def _is_valid_signature(token: str, timestamp, signature: str) -> bool:
    """Mailgun sends the timestamp as a string in a form post and as a number in JSON."""
    try:
        return validate_token(token, int(timestamp or 0), signature)
    except (TypeError, ValueError) as e:
        print(e)
        return False
