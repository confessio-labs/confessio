from datetime import datetime, timedelta

import boto3
from django.conf import settings
from django.urls import reverse
from django.utils.timezone import make_aware

from attaching.models import Image
from core.utils.discord_utils import send_discord_alert, DiscordChanel
from registry.models import Website
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


def upload_image(document, website: Website, request, comment: str | None = None,
                 ) -> tuple[Image | None, str | None]:
    if too_many_recent_images():
        subject = 'Too many images uploaded recently'
        send_email_to_admin(subject, subject)
        send_discord_alert(message=subject, channel=DiscordChanel.NEW_IMAGES)

        return None, "Trop d'images ont été téléchargées récemment. Veuillez réessayer plus tard."

    # Generate unique filename
    image_name = document.name.replace(' ', '_').replace('/', '_')
    user, user_agent, ip_address_hash = get_user_user_agent_and_ip(request)

    image = Image(
        website=website,
        name=image_name,
        comment=comment,
        user=user,
        user_agent=user_agent,
        ip_address_hash=ip_address_hash,
    )
    image.save()
    unique_filename = f"{image.uuid}/{image_name}"

    s3_success = upload_to_s3(document, unique_filename)
    if s3_success:
        print(f'Document uploaded successfully! unique_filename: {unique_filename}')

        if not user:
            website_url = request.build_absolute_uri(
                reverse('website_view', kwargs={'website_uuid': website.uuid})
            )
            email_body = (f"New image on website {website.name}\n"
                          f"url: {website_url}\n"
                          f"\n\ncomment:\n{comment}")
            subject = f'New image on confessio for {website.name}'
            send_email_to_admin(subject, email_body)
            send_discord_alert(message=email_body, channel=DiscordChanel.NEW_IMAGES)

        return image, None

    image.delete()

    return None, 'Une erreur est survenue lors du chargement du fichier.'


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


def get_image_public_url(image: Image) -> str:
    """Get the public URL of an image stored in S3."""
    host = f"{settings.AWS_STORAGE_BUCKET_NAME}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com"
    return f"https://{host}/{image.uuid}/{image.name}"


def too_many_recent_images() -> bool:
    last_30_days = datetime.now() - timedelta(days=30)
    recent_images_count = Image.objects.filter(created_at__gt=make_aware(last_30_days)).count()

    return recent_images_count > MAX_IMAGES_IN_30_DAYS
