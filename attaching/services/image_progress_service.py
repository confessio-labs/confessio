from uuid import UUID

from attaching.models import Image
from core.services.background_task_service import TaskStatus, get_task_status_by_first_arg

# Matches the @background task in attaching/tasks.py (module path + function name).
RECOGNIZE_IMAGE_TASK_NAME = 'attaching.tasks.worker_recognize_and_extract_image'


def get_image_recognition_status_by_website_uuid(website_uuids: set[str]
                                                 ) -> dict[str, TaskStatus]:
    """Map each website UUID owning an image with a pending/running recognition task to its
    TaskStatus. The task is keyed by image UUID, so we resolve those images back to their website.
    """
    if not website_uuids:
        return {}

    status_by_image_uuid = get_task_status_by_first_arg(RECOGNIZE_IMAGE_TASK_NAME)
    if not status_by_image_uuid:
        return {}

    image_uuids = []
    for arg in status_by_image_uuid:
        try:
            image_uuids.append(UUID(arg))
        except ValueError:  # not an image uuid, the queue row is not ours to read
            continue

    status_by_website_uuid: dict[str, TaskStatus] = {}
    for image_uuid, website_uuid in Image.objects.filter(uuid__in=image_uuids,
                                                         website_id__in=website_uuids)\
            .values_list('uuid', 'website_id'):
        status = status_by_image_uuid[str(image_uuid)]
        # IN_PROGRESS wins if a website has several pending images
        if status_by_website_uuid.get(str(website_uuid)) != TaskStatus.IN_PROGRESS:
            status_by_website_uuid[str(website_uuid)] = status
    return status_by_website_uuid
