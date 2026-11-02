from datetime import datetime
from enum import StrEnum
from uuid import UUID

from django.db import transaction
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from attaching.models import FileNote, FileNoteComment, FileNoteModeration, TextNote, \
    TextNoteComment, TextNoteModeration
from attaching.public_model import NoteTtl
from attaching.public_service import attaching_extract_text_note
from core.models.base_models import BaseUserReport
from core.utils.telegram_utils import TelegramTopic, send_telegram_alert
from front.models import Approval, ApprovalComment, ApprovalModeration, Issue, IssueComment, \
    IssueModeration
from registry.models import Church, Website
from registry.models.base_moderation_models import ModerationStatus
from core.services.admin_email_service import send_email_to_admin
from front.utils.web_utils import clean_email, find_error_in_email, \
    get_user_user_agent_and_ip, is_staff_user


class FeedbackType(StrEnum):
    GOOD = "good"
    ERROR = "error"
    COMMENT = "comment"


##############
# NEW REPORT #
##############

class NewReportError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def get_thread_head(website: Website, head_uuid: UUID | str
                    ) -> Issue | Approval | FileNote | TextNote:
    for head_class in (Issue, Approval, FileNote, TextNote):
        head = head_class.objects.filter(uuid=head_uuid, website=website).first()
        if head:
            return head

    # Threads are one level deep
    if any(comment_class.objects.filter(uuid=head_uuid).exists()
           for comment_class in (IssueComment, ApprovalComment, FileNoteComment,
                                 TextNoteComment)):
        raise NewReportError(400, 'Cannot reply to a reply')

    raise NewReportError(404, f'Report {head_uuid} does not exist')


def save_report(request: HttpRequest, website: Website, church: Church | None,
                feedback_type: FeedbackType, content: str | None,
                main_report_uuid: UUID | str | None, email: str | None = None
                ) -> Issue | Approval | IssueComment | ApprovalComment | FileNoteComment \
        | TextNoteComment:
    head = get_thread_head(website, main_report_uuid) if main_report_uuid else None

    if head:
        return save_comment(request, website, church, head, content, email)
    if feedback_type == FeedbackType.GOOD:
        return save_approval(request, website, church, content, email)
    return save_issue(request, website, church, content, email)


def save_issue(request: HttpRequest, website: Website, church: Church | None,
               content: str | None, email: str | None) -> Issue:
    user_fields = get_user_fields(request, email)
    issue = Issue.objects.create(website=website, church=church, content=content or '',
                                 **user_fields)
    if not user_fields['user']:
        notify_new_report(request, website, church, issue, False, content, email)

    return issue


def save_approval(request: HttpRequest, website: Website, church: Church | None,
                  content: str | None, email: str | None) -> Approval:
    user_fields = get_user_fields(request, email)
    approval = Approval.objects.create(website=website, church=church, content=content,
                                       **user_fields)
    if not user_fields['user']:
        notify_new_report(request, website, church, approval, False, content, email)

    return approval


def save_comment(request: HttpRequest, website: Website, church: Church | None,
                 head: Issue | Approval | FileNote | TextNote, content: str | None,
                 email: str | None
                 ) -> IssueComment | ApprovalComment | FileNoteComment | TextNoteComment:
    user_fields = get_user_fields(request, email)
    content = content or ''
    if isinstance(head, Approval):
        comment = ApprovalComment.objects.create(approval=head, content=content, **user_fields)
    elif isinstance(head, Issue):
        comment = IssueComment.objects.create(issue=head, content=content, **user_fields)
    elif isinstance(head, FileNote):
        comment = FileNoteComment.objects.create(file_note=head, content=content, **user_fields)
    else:
        comment = TextNoteComment.objects.create(text_note=head, content=content, **user_fields)

    if not user_fields['user']:
        notify_new_report(request, website, church, head, True, content, email)

    return comment


def get_user_fields(request: HttpRequest, email: str | None) -> dict:
    user, user_agent, ip_address_hash = get_user_user_agent_and_ip(request)
    return {
        'user': user,
        'user_agent': user_agent,
        'ip_address_hash': ip_address_hash,
        'email': email,
    }


def notify_new_report(request: HttpRequest, website: Website, church: Church | None,
                      head: Issue | Approval | FileNote | TextNote, is_comment: bool,
                      content: str | None, email: str | None):
    # A thumbs-up with no content says nothing a moderator could act on
    if isinstance(head, Approval) and not is_comment and not content:
        return

    add_necessary_moderation(website, head, is_comment=is_comment)

    website_url = request.build_absolute_uri(
        reverse('website_view', kwargs={'website_uuid': website.uuid})
    )

    thread_type = get_thread_type(head)
    label = f'{thread_type} comment' if is_comment else thread_type
    email_body = (f"New {label} on website {website.name}\n"
                  f"url: {website_url}\n"
                  + (f"church: {church.name}\n" if church else "")
                  + (f"email: {email}\n" if email else "")
                  + f"\ncontent:\n{content}")
    subject = f'New {label} on confessio for {website.name}'
    send_email_to_admin(subject, email_body)
    send_telegram_alert(message=email_body, topic=TelegramTopic.NEW_REPORTS)


def get_thread_type(head: Issue | Approval | FileNote | TextNote) -> str:
    if isinstance(head, Issue):
        return 'issue'
    if isinstance(head, Approval):
        return 'approval'
    if isinstance(head, FileNote):
        return 'file_note'
    return 'text_note'


def new_report(request, website: Website) -> str:
    feedback_type_str = request.POST.get('feedback_type')
    content = request.POST.get('comment')
    main_report_uuid = request.POST.get('main_report_uuid')
    email = clean_email(request.POST.get('email'))

    if not feedback_type_str:
        raise NewReportError(400, 'Feedback type is None')

    try:
        feedback_type = FeedbackType(feedback_type_str)
    except ValueError:
        raise NewReportError(400, f'Invalid feedback type: {feedback_type_str}')

    email_error = find_error_in_email(email)
    if email_error:
        raise NewReportError(400, email_error)

    save_report(request, website, None, feedback_type, content, main_report_uuid, email)

    if is_staff_user(request) and request.POST.get('mark_solved') and main_report_uuid:
        head = get_thread_head(website, main_report_uuid)
        if isinstance(head, Issue):
            solve_issue(head)

    return 'Merci pour votre retour !'


def add_necessary_moderation(website: Website, head: Issue | Approval | FileNote | TextNote,
                             is_comment: bool):
    if isinstance(head, Approval):
        category = ApprovalModeration.Category.NEW_COMMENT if is_comment \
            else ApprovalModeration.Category.NEW_APPROVAL
        moderation_class, thread_field = ApprovalModeration, 'approval'
    elif isinstance(head, FileNote):
        # A new note is flagged on upload, only comments reach this function
        category = FileNoteModeration.Category.NEW_COMMENT
        moderation_class, thread_field = FileNoteModeration, 'file_note'
    elif isinstance(head, TextNote):
        category = TextNoteModeration.Category.NEW_COMMENT
        moderation_class, thread_field = TextNoteModeration, 'text_note'
    else:
        category = IssueModeration.Category.NEW_COMMENT if is_comment \
            else IssueModeration.Category.NEW_ISSUE
        moderation_class, thread_field = IssueModeration, 'issue'

    # One moderation per thread and category: a new comment reopens it
    moderation, created = moderation_class.objects.get_or_create(
        **{thread_field: head},
        category=category,
        defaults={'diocese': website.get_diocese(), 'status': ModerationStatus.TO_VALIDATE},
    )
    if not created and moderation.status != ModerationStatus.TO_VALIDATE:
        moderation.status = ModerationStatus.TO_VALIDATE
        moderation.save()


###############
# SOLVE ISSUE #
###############

# Moderation statuses are set directly: IssueModeration.set_status would write back to the issue

def solve_issue(issue: Issue):
    if issue.solved_at is None:
        issue.solved_at = timezone.now()
        issue.save()

    for moderation in issue.moderations.exclude(status=ModerationStatus.VALIDATED):
        moderation.status = ModerationStatus.VALIDATED
        moderation.save()


def unsolve_issue(issue: Issue):
    if issue.solved_at is not None:
        issue.solved_at = None
        issue.save()

    for moderation in issue.moderations.filter(status=ModerationStatus.VALIDATED):
        moderation.status = ModerationStatus.TO_VALIDATE
        moderation.save()


##################
# CONVERT REPORT #
##################

# uuids and created_at are kept, so that the thread keeps its links and its place

ISSUE_CATEGORY_BY_TEXT_NOTE_CATEGORY = {
    TextNoteModeration.Category.NEW_TEXT_NOTE: IssueModeration.Category.NEW_ISSUE,
    TextNoteModeration.Category.NEW_COMMENT: IssueModeration.Category.NEW_COMMENT,
}
TEXT_NOTE_CATEGORY_BY_ISSUE_CATEGORY = {
    issue_category: text_note_category
    for text_note_category, issue_category in ISSUE_CATEGORY_BY_TEXT_NOTE_CATEGORY.items()
}


def get_user_report_fields(report: BaseUserReport) -> dict:
    return {
        'user_id': report.user_id,
        'user_agent': report.user_agent,
        'ip_address_hash': report.ip_address_hash,
        'email': report.email,
    }


def create_with_created_at(model_class, created_at: datetime, **fields):
    instance = model_class.objects.create(**fields)
    # auto_now_add overrides any created_at given to create()
    model_class.objects.filter(pk=instance.pk).update(created_at=created_at)
    instance.created_at = created_at
    return instance


@transaction.atomic
def convert_text_note_to_issue(text_note: TextNote) -> Issue:
    moderations = list(text_note.moderations.all())
    # Same rule as IssueModeration.validate: a validated moderation means a solved issue
    is_solved = any(m.status == ModerationStatus.VALIDATED for m in moderations)
    issue = create_with_created_at(
        Issue, text_note.created_at,
        uuid=text_note.uuid,
        website_id=text_note.website_id,
        church_id=text_note.church_id,
        content=text_note.content,
        solved_at=timezone.now() if is_solved else None,
        **get_user_report_fields(text_note),
    )

    for comment in text_note.comments.all():
        create_with_created_at(
            IssueComment, comment.created_at,
            uuid=comment.uuid, issue=issue, content=comment.content,
            **get_user_report_fields(comment),
        )

    diocese = text_note.website.get_diocese()
    for moderation in moderations:
        create_with_created_at(
            IssueModeration, moderation.created_at,
            issue=issue,
            category=ISSUE_CATEGORY_BY_TEXT_NOTE_CATEGORY[moderation.category],
            status=moderation.status,
            comment=moderation.comment,
            diocese=diocese,
        )

    # its pre_delete signal re-inits the scheduling, which drops the text note prunings
    text_note.delete()

    return issue


@transaction.atomic
def convert_issue_to_text_note(issue: Issue, ttl: NoteTtl) -> TextNote:
    text_note = create_with_created_at(
        TextNote, issue.created_at,
        uuid=issue.uuid,
        website_id=issue.website_id,
        church_id=issue.church_id,
        content=issue.content,
        expire_at=timezone.now() + ttl.duration,
        **get_user_report_fields(issue),
    )

    for comment in issue.comments.all():
        create_with_created_at(
            TextNoteComment, comment.created_at,
            uuid=comment.uuid, text_note=text_note, content=comment.content,
            **get_user_report_fields(comment),
        )

    diocese = issue.website.get_diocese()
    for moderation in issue.moderations.all():
        create_with_created_at(
            TextNoteModeration, moderation.created_at,
            text_note=text_note,
            category=TEXT_NOTE_CATEGORY_BY_ISSUE_CATEGORY[moderation.category],
            status=moderation.status,
            comment=moderation.comment,
            diocese=diocese,
        )

    issue.delete()

    transaction.on_commit(lambda: attaching_extract_text_note(text_note))

    return text_note


##################
# COUNT & LABELS #
##################

def get_count_and_label(website: Website):
    # Filtered in Python to reuse the prefetched issues
    issues = website.issues.all()
    # A solved issue means the data is now right
    solved_issue_count = sum(1 for issue in issues if issue.solved_at is not None)

    count_and_label = []
    for count, label, singular_tooltip, plural_tooltip in [
        (len(website.approvals.all()) + solved_issue_count, '👍', 'avis positif', 'avis positifs'),
        (len(issues) - solved_issue_count, '👎', 'erreur signalée', 'erreurs signalées'),
    ]:
        if count:
            count_and_label.append({
                'count': count,
                'label': label,
                'tooltip': singular_tooltip if count <= 1 else plural_tooltip
            })

    return count_and_label
