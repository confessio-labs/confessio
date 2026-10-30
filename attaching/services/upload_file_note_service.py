import mimetypes
from datetime import datetime, timedelta

import boto3
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import make_aware

from attaching.models import FileNote
from attaching.public_model import NoteTtl
from attaching.services.file_note_moderation_service import \
    add_necessary_moderation_for_file_note
from core.utils.telegram_utils import TelegramTopic, send_telegram_alert
from registry.models import Church, Website
from core.services.admin_email_service import send_email_to_admin
from front.utils.web_utils import get_user_user_agent_and_ip


IMAGE_SIZE_LIMIT = 10 * 1024 * 1024  # 10MB limit for uploaded images
MAX_IMAGES_IN_30_DAYS = 2000  # Maximum number of images allowed in the last 30 days
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
ALLOWED_IMAGE_MIME_TYPES = {'image/jpeg', 'image/png', 'image/webp'}


def find_error_in_document_to_upload(document) -> str | None:
    # validate that the document is not empty
    if not document or document.size == 0:
        return "Merci de sélectionner une image ou de prendre une photo."

    # Validate file size
    if document.size > IMAGE_SIZE_LIMIT:
        return "Le fichier ne doit pas dépasser 10 Mo."

    # Validate image format (OpenAI only accepts jpeg/png/webp/gif). The extension is the
    # primary gate; the browser-reported content type is only enforced when it declares a
    # specific type (a generic/empty one, e.g. application/octet-stream, is treated as unknown
    # so we don't falsely reject a valid image).
    name = document.name or ''
    extension = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    content_type = (document.content_type or '').lower()
    mime_declared = content_type not in ('', 'application/octet-stream')
    if extension not in ALLOWED_IMAGE_EXTENSIONS or (
            mime_declared and content_type not in ALLOWED_IMAGE_MIME_TYPES):
        return ("Format d'image non supporté. "
                "Merci d'utiliser une image au format JPG, PNG ou WEBP.")

    return None


def upload_file_note(document, website: Website, request, ttl: NoteTtl,
                     caption: str | None = None, email: str | None = None,
                     church: Church | None = None) -> tuple[FileNote | None, str | None]:
    if too_many_recent_file_notes():
        subject = 'Too many images uploaded recently'
        send_email_to_admin(subject, subject)
        send_telegram_alert(message=subject, topic=TelegramTopic.NEW_IMAGES)

        return None, "Trop d'images ont été téléchargées récemment. Veuillez réessayer plus tard."

    # Generate unique filename
    image_name = document.name.replace(' ', '_').replace('/', '_')
    user, user_agent, ip_address_hash = get_user_user_agent_and_ip(request)

    file_note = FileNote(
        website=website,
        church=church,
        name=image_name,
        caption=caption,
        mime_type=get_mime_type(document, image_name),
        expire_at=timezone.now() + ttl.duration,
        user=user,
        user_agent=user_agent,
        ip_address_hash=ip_address_hash,
        email=email,
    )
    file_note.save()
    unique_filename = f"{file_note.uuid}/{image_name}"

    s3_success = upload_to_s3(document, unique_filename)
    if s3_success:
        print(f'Document uploaded successfully! unique_filename: {unique_filename}')

        if not user:
            add_necessary_moderation_for_file_note(file_note)

            website_url = request.build_absolute_uri(
                reverse('website_view', kwargs={'website_uuid': website.uuid})
            )
            email_body = (f"New image on website {website.name}\n"
                          f"url: {website_url}\n"
                          + (f"email: {email}\n" if email else "")
                          + f"\n\ncomment:\n{caption}")
            subject = f'New image on confessio for {website.name}'
            send_email_to_admin(subject, email_body)
            send_telegram_alert(message=email_body, topic=TelegramTopic.NEW_IMAGES)

        return file_note, None

    file_note.delete()

    return None, 'Une erreur est survenue lors du chargement du fichier.'


def get_mime_type(document, name: str) -> str:
    content_type = (document.content_type or '').lower()
    if content_type in ALLOWED_IMAGE_MIME_TYPES:
        return content_type
    return mimetypes.guess_type(name)[0] or 'application/octet-stream'


def upload_to_s3(file, filename) -> bool:
    """Upload file to S3 bucket"""
    s3_client = boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME
    )

    try:
        # Upload file to S3
        s3_client.upload_fileobj(
            file,
            settings.AWS_STORAGE_BUCKET_NAME,
            filename,
        )

        return True
    except Exception as e:
        print(e)
        return False


def get_file_note_public_url(file_note: FileNote) -> str:
    """Get the public URL of a file note stored in S3."""
    host = f"{settings.AWS_STORAGE_BUCKET_NAME}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com"
    return f"https://{host}/{file_note.uuid}/{file_note.name}"


def too_many_recent_file_notes() -> bool:
    last_30_days = datetime.now() - timedelta(days=30)
    recent_images_count = FileNote.objects.filter(created_at__gt=make_aware(last_30_days)).count()

    return recent_images_count > MAX_IMAGES_IN_30_DAYS
