from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.html import linebreaks

from attaching.models import TextNote
from attaching.services.text_note_moderation_service import \
    add_necessary_moderation_for_text_note
from attaching.services.upload_file_note_service import NOTE_DEFAULT_TTL
from core.services.admin_email_service import send_email_to_admin
from core.utils.telegram_utils import TelegramTopic, send_telegram_alert
from front.utils.web_utils import get_user_user_agent_and_ip
from registry.models import Website

TEXT_NOTE_MAX_LENGTH = 10000
MAX_TEXT_NOTES_IN_30_DAYS = 2000


def find_error_in_text_note_content(content: str | None) -> str | None:
    if not content or not content.strip():
        return "Merci de saisir des horaires."

    if len(content) > TEXT_NOTE_MAX_LENGTH:
        return f"Le texte ne doit pas dépasser {TEXT_NOTE_MAX_LENGTH} caractères."

    return None


def add_text_note(content: str, website: Website, request, email: str | None = None
                  ) -> tuple[TextNote | None, str | None]:
    if too_many_recent_text_notes():
        subject = 'Too many text notes added recently'
        send_email_to_admin(subject, subject)
        send_telegram_alert(message=subject, topic=TelegramTopic.NEW_REPORTS)

        return None, "Trop de textes ont été ajoutés récemment. Veuillez réessayer plus tard."

    user, user_agent, ip_address_hash = get_user_user_agent_and_ip(request)

    text_note = TextNote.objects.create(
        website=website,
        content=content,
        expire_at=timezone.now() + NOTE_DEFAULT_TTL,
        user=user,
        user_agent=user_agent,
        ip_address_hash=ip_address_hash,
        email=email,
    )

    if not user:
        add_necessary_moderation_for_text_note(text_note)

        website_url = request.build_absolute_uri(
            reverse('website_view', kwargs={'website_uuid': website.uuid})
        )
        email_body = (f"New text note on website {website.name}\n"
                      f"url: {website_url}\n"
                      + (f"email: {email}\n" if email else "")
                      + f"\n\ncontent:\n{content}")
        subject = f'New text note on confessio for {website.name}'
        send_email_to_admin(subject, email_body)
        send_telegram_alert(message=email_body, topic=TelegramTopic.NEW_REPORTS)

    return text_note, None


def get_text_note_html(text_note: TextNote) -> str:
    return linebreaks(text_note.content, autoescape=True)


def too_many_recent_text_notes() -> bool:
    last_30_days = timezone.now() - timedelta(days=30)
    return TextNote.objects.filter(created_at__gt=last_30_days).count() > MAX_TEXT_NOTES_IN_30_DAYS
