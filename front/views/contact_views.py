import os
from email.utils import formataddr

from botocore.exceptions import ClientError
from django.conf import settings
from django.core.mail import EmailMessage, BadHeaderError
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.translation import gettext
from django.views.decorators.csrf import csrf_exempt

from core.utils.discord_utils import send_discord_alert, DiscordChanel
from front.services.card.scraping_url_service import quote_path, unquote_path
from front.services.messaging.messaging_service import ingest_inbound_email
from front.utils.cloudflare_utils import verify_token
from front.utils.mailgun_utils import validate_token
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

        # SES only accepts a verified identity as From, so we send from DEFAULT_FROM_EMAIL and
        # put the visitor in Reply-To.
        # We might want to put the sender first in the body because mailgun's stripped-text
        # drops trailing signature-looking blocks before the webhook sees them.
        email_body = f"{message}\n\n{name}"
        try:
            EmailMessage(
                subject=subject,
                body=email_body,
                from_email=formataddr((f'{name} (via Confessio)', settings.DEFAULT_FROM_EMAIL)),
                to=[os.environ.get('CONTACT_EMAIL')],
                reply_to=[formataddr((name, from_email))],
            ).send()
        except (BadHeaderError, ClientError) as e:
            print(e)
            name_text = quote_path(name)
            message_subject = quote_path(subject)
            message_text = quote_path(message)
            return redirect("contact_failure", message='failure',
                            name_text=name_text, email=from_email,
                            message_subject=message_subject, message_text=message_text)

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
def contact_mail_webhook(request):
    if request.method != 'POST':
        return HttpResponse(status=405)

    token = request.POST.get('token', '')
    timestamp = int(request.POST.get('timestamp', 0))
    signature = request.POST.get('signature', '')

    if not validate_token(token, timestamp, signature):
        return HttpResponse(status=403)

    reply_to = request.POST.get('Reply-To', '')
    recipient = request.POST.get('recipient', '')
    from_header = request.POST.get('from', '')
    subject = request.POST.get('subject', '')
    body_plain = request.POST.get('body-plain', '')
    stripped_text = request.POST.get('stripped-text', '')

    email_body = (f"FROM:{from_header}\nTO:{recipient}\nREPLY-TO:{reply_to}\n"
                  f"SUBJECT:{subject}\n\n{stripped_text or body_plain}"
                  )

    if recipient == os.environ.get('CONTACT_EMAIL'):
        # A contact form submission lands here too: it is mailed to CONTACT_EMAIL, which Mailgun
        # routes back to this webhook. So this is the single entry point of the admin messaging,
        # and the contact view has nothing to do.
        try:
            message = ingest_inbound_email(from_header, reply_to, subject,
                                           body_plain, stripped_text)
        except Exception as e:
            # Never fail the webhook on an ingestion problem: Mailgun would retry the delivery.
            print(e)
            message = None

        if message:
            conversation_url = settings.REQUEST_BASE_URL + reverse(
                'messaging_view', args=[message.conversation_id])
            email_body += f"\n\n{conversation_url}"

        send_discord_alert(message=email_body, channel=DiscordChanel.CONTACT_FORM)

    return HttpResponse(status=200)
