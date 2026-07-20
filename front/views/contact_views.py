import os

from django.core.mail import send_mail, BadHeaderError
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.utils.translation import gettext
from django.views.decorators.csrf import csrf_exempt

from core.utils.discord_utils import send_discord_alert, DiscordChanel
from front.services.card.scraping_url_service import quote_path, unquote_path
from front.utils.cloudflare_utils import verify_token
from front.utils.mailgun_utils import validate_token
from registry.models import Diocese, Website
from scheduling.models import IndexEvent


def contact(request, message=None, email=None, name_text=None, message_text=None):
    if request.method == "GET":
        cloudflare_turnstile_site_key = os.environ.get('CLOUDFLARE_TURNSTILE_SITE_KEY', '')
        return render(request, 'pages/contact.html',
                      {'message': message,
                       'name_text': unquote_path(name_text or ''),
                       'email': email or '',
                       'message_text': unquote_path(message_text or ''),
                       'meta_title': gettext('contactPageTitle'),
                       'cloudflare_turnstile_site_key': cloudflare_turnstile_site_key
                       })
    else:
        name = request.POST.get('name')
        from_email = request.POST.get('email')
        message = request.POST.get('message')

        if not name or not from_email or not message:
            return HttpResponseBadRequest("Missing required fields")

        cloudflare_token = request.POST.get('cf-turnstile-response')
        if not verify_token(cloudflare_token):
            name_text = quote_path(name)
            message_text = quote_path(message)
            return redirect("contact_failure", message='failure',
                            name_text=name_text, email=from_email, message_text=message_text)

        email_body = f"{from_email}\n{name}\n\n{message}"
        subject = f'New message from {name} on confessio'
        try:
            send_mail(subject,
                      email_body,
                      None,  # Default to DEFAULT_FROM_EMAIL
                      [os.environ.get('CONTACT_FORWARD_EMAIL')])
        except BadHeaderError as e:
            print(e)
            name_text = quote_path(name)
            message_text = quote_path(message)
            return redirect("contact_failure", message='failure',
                            name_text=name_text, email=from_email, message_text=message_text)

        send_discord_alert(message=email_body, channel=DiscordChanel.CONTACT_FORM)

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

    sender = request.POST.get('sender', '')
    recipient = request.POST.get('recipient', '')
    from_header = request.POST.get('from', '')
    subject = request.POST.get('subject', '')
    body_plain = request.POST.get('body-plain', '')
    stripped_text = request.POST.get('stripped-text', '')

    email_body = (f"FROM:{from_header} <{sender}>\nTO:{recipient}\n"
                  f"SUBJECT:{subject}\n\n{stripped_text or body_plain}"
                  )

    if recipient == os.environ.get('CONTACT_EMAIL'):
        send_discord_alert(message=email_body, channel=DiscordChanel.CONTACT_FORM)

    return HttpResponse(status=200)
