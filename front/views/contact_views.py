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
from front.utils.mailgun_utils import validate_token
from front.utils.messaging_utils import is_same_email
from registry.models import Diocese, Website
from scheduling.models import IndexEvent


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
def mail_received_webhook(request):
    """The single Mailgun inbound route, for both addresses it delivers to us.

    CONTACT_EMAIL carries what correspondents write to us. ARCHIVE_EMAIL carries the copy the
    contact mailbox puts on what it sends: Mailgun keeps nothing of what our domain sends, so being
    sent a copy is the only way we get to see a reply written outside /messaging.
    """
    if request.method != 'POST':
        return HttpResponse(status=405)

    if not _is_valid_signature(request.POST.get('token', ''),
                               request.POST.get('timestamp', ''),
                               request.POST.get('signature', '')):
        return HttpResponse(status=403)

    recipient = request.POST.get('recipient', '')
    from_header = request.POST.get('from', '')
    subject = request.POST.get('subject', '')
    body_plain = request.POST.get('body-plain', '')
    stripped_text = request.POST.get('stripped-text', '')
    # The footer shows the admin link as a word, so on a quoted reply the url is in the href only.
    body_html = request.POST.get('body-html', '')
    message_id = request.POST.get('Message-Id', '')
    in_reply_to = request.POST.get('In-Reply-To', '')
    references = request.POST.get('References', '')

    if is_same_email(recipient, os.environ.get('ARCHIVE_EMAIL', '')):
        try:
            # `To` names the correspondent; `recipient` is the archive address we were routed on.
            ingest_sent_email(from_header=from_header,
                              to_header=request.POST.get('To', ''),
                              subject=subject,
                              body_plain=body_plain,
                              stripped_text=stripped_text,
                              body_html=body_html,
                              message_id=message_id,
                              in_reply_to=in_reply_to,
                              references=references)
        except Exception as e:
            # Never fail the webhook on an ingestion problem: Mailgun would retry the delivery. No
            # Discord alert here — this is us talking, and it is already in the mailbox.
            print(e)
        return HttpResponse(status=200)

    if not is_same_email(recipient, os.environ.get('CONTACT_EMAIL', '')):
        return HttpResponse(status=200)

    # The mails we mirror to the contact mailbox come back through this route. They are already in
    # the conversation, and no-reply@ is by construction an address only we send from.
    if is_same_email(from_header, settings.DEFAULT_FROM_EMAIL):
        return HttpResponse(status=200)

    try:
        ingest_received_email(request,
                              from_header=from_header,
                              reply_to=request.POST.get('Reply-To', ''),
                              subject=subject,
                              body_plain=body_plain,
                              stripped_text=stripped_text,
                              body_html=body_html,
                              message_id=message_id,
                              in_reply_to=in_reply_to,
                              references=references)
    except Exception as e:
        # Never fail the webhook on an ingestion problem: Mailgun would retry the delivery. Ring
        # Discord with the raw mail instead — the conversation is lost, the message must not be.
        print(e)
        send_discord_alert(
            message=f"Mail entrant non enregistré ({e})\n\n"
                    f"FROM:{from_header}\nSUBJECT:{subject}\n\n{stripped_text or body_plain}",
            channel=DiscordChanel.CONTACT_FORM)

    return HttpResponse(status=200)


def _is_valid_signature(token: str, timestamp, signature: str) -> bool:
    """Mailgun sends the timestamp as a string in a form post and as a number in JSON."""
    try:
        return validate_token(token, int(timestamp or 0), signature)
    except (TypeError, ValueError) as e:
        print(e)
        return False
