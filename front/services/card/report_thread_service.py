from dataclasses import dataclass
from uuid import UUID

from attaching.models import FileNote, FileNoteComment, FileNoteModeration, TextNote, \
    TextNoteComment, TextNoteModeration
from front.models import Approval, ApprovalComment, ApprovalModeration, Issue, IssueComment, \
    IssueModeration
from registry.models import Website
from registry.models.base_moderation_models import ModerationMixin


@dataclass
class ReportThread:
    head: Issue | Approval | FileNote | TextNote
    comments: list[IssueComment | ApprovalComment | FileNoteComment | TextNoteComment]

    @property
    def emails(self) -> list[str]:
        return list(dict.fromkeys(message.email for message in [self.head, *self.comments]
                                  if message.email))

    @property
    def is_approval(self) -> bool:
        return isinstance(self.head, Approval)

    @property
    def is_issue(self) -> bool:
        return isinstance(self.head, Issue)

    @property
    def is_file_note(self) -> bool:
        return isinstance(self.head, FileNote)

    @property
    def is_text_note(self) -> bool:
        return isinstance(self.head, TextNote)


def get_report_threads(website: Website) -> list[ReportThread]:
    heads = list(Issue.objects.filter(website=website).prefetch_related('comments__user')) \
        + list(Approval.objects.filter(website=website).prefetch_related('comments__user')) \
        + list(FileNote.objects.filter(website=website).prefetch_related('comments__user')) \
        + list(TextNote.objects.filter(website=website).prefetch_related('comments__user'))
    heads.sort(key=lambda head: head.created_at, reverse=True)

    return [ReportThread(head=head,
                         comments=sorted(head.comments.all(), key=lambda c: c.created_at))
            for head in heads]


# Every moderation class names its comment category the same
COMMENT_MODERATION_CATEGORY = 'new_comment'


def get_moderations_by_thread_uuid(threads: list[ReportThread]
                                   ) -> tuple[dict[UUID, list[ModerationMixin]],
                                              dict[UUID, list[ModerationMixin]]]:
    """Return (head moderations, comment moderations) by thread uuid."""
    head_uuids = [thread.head.uuid for thread in threads]

    moderations_and_thread_uuids = \
        [(m, m.issue_id) for m in IssueModeration.objects.filter(issue_id__in=head_uuids)] \
        + [(m, m.approval_id)
           for m in ApprovalModeration.objects.filter(approval_id__in=head_uuids)] \
        + [(m, m.file_note_id)
           for m in FileNoteModeration.objects.filter(file_note_id__in=head_uuids)] \
        + [(m, m.text_note_id)
           for m in TextNoteModeration.objects.filter(text_note_id__in=head_uuids)]

    head_moderations_by_thread_uuid = {}
    comment_moderations_by_thread_uuid = {}
    for moderation, thread_uuid in moderations_and_thread_uuids:
        moderations_by_thread_uuid = comment_moderations_by_thread_uuid \
            if moderation.category == COMMENT_MODERATION_CATEGORY \
            else head_moderations_by_thread_uuid
        moderations_by_thread_uuid.setdefault(thread_uuid, []).append(moderation)

    return head_moderations_by_thread_uuid, comment_moderations_by_thread_uuid
