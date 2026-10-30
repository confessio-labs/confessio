from attaching.models import FileNote, FileNoteModeration, TextNote, TextNoteModeration
from attaching.services.file_note_moderation_service import get_new_file_note_moderation
from attaching.services.file_note_progress_service import \
    get_file_note_recognition_status_by_website_uuid
from attaching.services.upload_file_note_service import upload_file_note, \
    get_file_note_public_url, find_error_in_document_to_upload
from attaching.services.text_note_moderation_service import get_new_text_note_moderation
from attaching.services.text_note_service import add_text_note, find_error_in_text_note_content
from attaching.services.worker_recognize_service import recognize_pdf
from attaching.tasks import worker_recognize_and_extract_file_note, worker_extract_text_note
from core.services.background_task_service import TaskStatus
from registry.models import Church, Website


def attaching_upload_file_note(document, website: Website, request, caption: str | None = None,
                               email: str | None = None, church: Church | None = None
                               ) -> tuple[FileNote | None, str | None]:
    return upload_file_note(document, website, request, caption=caption, email=email,
                            church=church)


def attaching_find_error_in_document_to_upload(document) -> str | None:
    return find_error_in_document_to_upload(document)


def attaching_recognize_and_extract_file_note(file_note: FileNote):
    worker_recognize_and_extract_file_note(str(file_note.uuid))


def attaching_get_file_note_public_url(file_note: FileNote) -> str:
    return get_file_note_public_url(file_note)


def attaching_get_new_file_note_moderation(file_note: FileNote) -> FileNoteModeration | None:
    return get_new_file_note_moderation(file_note)


def attaching_add_text_note(content: str, website: Website, request, email: str | None = None,
                            church: Church | None = None) -> tuple[TextNote | None, str | None]:
    return add_text_note(content, website, request, email, church)


def attaching_find_error_in_text_note_content(content: str | None) -> str | None:
    return find_error_in_text_note_content(content)


def attaching_extract_text_note(text_note: TextNote):
    worker_extract_text_note(str(text_note.uuid))


def attaching_get_new_text_note_moderation(text_note: TextNote) -> TextNoteModeration | None:
    return get_new_text_note_moderation(text_note)


def attaching_recognize_pdf(pdf_url: str, pdf_bytes: bytes) -> str | None:
    return recognize_pdf(pdf_url, pdf_bytes)


def attaching_get_file_note_recognition_status_by_website_uuid(
        website_uuids: set[str]) -> dict[str, TaskStatus]:
    return get_file_note_recognition_status_by_website_uuid(website_uuids)
