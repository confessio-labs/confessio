from enum import StrEnum
from uuid import UUID

from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from attaching.models import FileNote, FileNoteComment, FileNoteModeration, TextNote, \
    TextNoteComment, TextNoteModeration
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
                feedback_type: FeedbackType, comment: str | None,
                main_report_uuid: UUID | str | None, email: str | None = None
                ) -> Issue | Approval | IssueComment | ApprovalComment | FileNoteComment \
        | TextNoteComment:
    head = get_thread_head(website, main_report_uuid) if main_report_uuid else None

    user, user_agent, ip_address_hash = get_user_user_agent_and_ip(request)
    user_fields = {
        'user': user,
        'user_agent': user_agent,
        'ip_address_hash': ip_address_hash,
        'email': email,
    }

    if isinstance(head, Approval):
        report = ApprovalComment.objects.create(approval=head, content=comment or '',
                                                **user_fields)
    elif isinstance(head, Issue):
        report = IssueComment.objects.create(issue=head, content=comment or '', **user_fields)
    elif isinstance(head, FileNote):
        report = FileNoteComment.objects.create(file_note=head, content=comment or '',
                                                **user_fields)
    elif isinstance(head, TextNote):
        report = TextNoteComment.objects.create(text_note=head, content=comment or '',
                                                **user_fields)
    elif feedback_type == FeedbackType.GOOD:
        report = Approval.objects.create(website=website, church=church, content=comment,
                                         **user_fields)
    else:
        report = Issue.objects.create(website=website, church=church, content=comment or '',
                                      **user_fields)

    if not user:
        add_necessary_moderation(website, head or report, is_comment=head is not None)

        website_url = request.build_absolute_uri(
            reverse('website_view', kwargs={'website_uuid': website.uuid})
        )

        email_body = (f"New report on website {website.name}\n"
                      f"url: {website_url}\n"
                      + (f"church: {church.name}\n" if church else "")
                      + (f"email: {email}\n" if email else "")
                      + f"feedback_type: {feedback_type}\n\ncomment:\n{comment}")
        subject = f'New report on confessio for {website.name}'
        send_email_to_admin(subject, email_body)
        send_telegram_alert(message=email_body, topic=TelegramTopic.NEW_REPORTS)

    return report


def new_report(request, website: Website) -> str:
    feedback_type_str = request.POST.get('feedback_type')
    comment = request.POST.get('comment')
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

    save_report(request, website, None, feedback_type, comment, main_report_uuid, email)

    if is_staff_user(request) and request.POST.get('mark_solved') and main_report_uuid:
        head = get_thread_head(website, main_report_uuid)
        if isinstance(head, Issue):
            solve_issue(head)

    return 'Merci pour votre retour !'


def add_necessary_moderation(website: Website, head: Issue | Approval | FileNote | TextNote,
                             is_comment: bool):
    if isinstance(head, Approval):
        # A thumbs-up with no comment says nothing a moderator could act on
        if not is_comment and not head.content:
            return
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
