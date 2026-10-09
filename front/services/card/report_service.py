from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from django.http import HttpRequest
from django.urls import reverse

from core.utils.telegram_utils import TelegramTopic, send_telegram_alert
from front.models import Approval, ApprovalComment, ApprovalModeration, Issue, IssueComment, \
    IssueModeration
from registry.models import Church, Website
from registry.models.base_moderation_models import ModerationStatus, ModerationMixin
from core.services.admin_email_service import send_email_to_admin
from front.utils.web_utils import get_user_user_agent_and_ip


class FeedbackType(StrEnum):
    GOOD = "good"
    ERROR = "error"
    COMMENT = "comment"


class ErrorType(StrEnum):
    OUTDATED = "outdated"
    CHURCHES = "churches"
    PARAGRAPHS = "paragraphs"
    SCHEDULES = "schedules"


##############
# NEW REPORT #
##############

class NewReportError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def get_thread_head(website: Website, head_uuid: UUID | str) -> Issue | Approval:
    issue = Issue.objects.filter(uuid=head_uuid, website=website).first()
    if issue:
        return issue

    approval = Approval.objects.filter(uuid=head_uuid, website=website).first()
    if approval:
        return approval

    # Threads are one level deep
    if IssueComment.objects.filter(uuid=head_uuid).exists() \
            or ApprovalComment.objects.filter(uuid=head_uuid).exists():
        raise NewReportError(400, 'Cannot reply to a reply')

    raise NewReportError(404, f'Report {head_uuid} does not exist')


def save_report(request: HttpRequest, website: Website, church: Church | None,
                feedback_type: FeedbackType, error_type: ErrorType | None,
                comment: str | None, main_report_uuid: UUID | str | None
                ) -> Issue | Approval | IssueComment | ApprovalComment:
    head = get_thread_head(website, main_report_uuid) if main_report_uuid else None

    user, user_agent, ip_address_hash = get_user_user_agent_and_ip(request)
    user_fields = {
        'user': user,
        'user_agent': user_agent,
        'ip_address_hash': ip_address_hash,
    }

    if isinstance(head, Approval):
        report = ApprovalComment.objects.create(approval=head, content=comment or '',
                                                **user_fields)
    elif isinstance(head, Issue):
        report = IssueComment.objects.create(issue=head, content=comment or '', **user_fields)
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
                      + f"feedback_type: {feedback_type}\n"
                      f"error_type: {error_type}\n\ncomment:\n{comment}")
        subject = f'New report on confessio for {website.name}'
        send_email_to_admin(subject, email_body)
        send_telegram_alert(message=email_body, topic=TelegramTopic.NEW_REPORTS)

    return report


def new_report(request, website: Website) -> str:
    feedback_type_str = request.POST.get('feedback_type')
    error_type_str = request.POST.get('error_type')
    comment = request.POST.get('comment')
    main_report_uuid = request.POST.get('main_report_uuid')

    if not feedback_type_str:
        raise NewReportError(400, 'Feedback type is None')

    try:
        feedback_type = FeedbackType(feedback_type_str)
    except ValueError:
        raise NewReportError(400, f'Invalid feedback type: {feedback_type_str}')

    try:
        error_type = ErrorType(error_type_str) if error_type_str else None
    except ValueError:
        raise NewReportError(400, f'Invalid error type: {error_type_str}')

    save_report(request, website, None, feedback_type, error_type, comment, main_report_uuid)

    return 'Merci pour votre retour !'


def add_necessary_moderation(website: Website, head: Issue | Approval, is_comment: bool):
    if isinstance(head, Approval):
        # A thumbs-up with no comment says nothing a moderator could act on
        if not is_comment and not head.content:
            return
        category = ApprovalModeration.Category.NEW_COMMENT if is_comment \
            else ApprovalModeration.Category.NEW_APPROVAL
        moderation_class, thread_field = ApprovalModeration, 'approval'
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


####################
# PREVIOUS REPORTS #
####################

@dataclass
class ReportThread:
    head: Issue | Approval
    comments: list[IssueComment | ApprovalComment]

    @property
    def is_approval(self) -> bool:
        return isinstance(self.head, Approval)


def get_report_threads(website: Website) -> list[ReportThread]:
    heads = list(Issue.objects.filter(website=website).prefetch_related('comments__user')) \
        + list(Approval.objects.filter(website=website).prefetch_related('comments__user'))
    heads.sort(key=lambda head: head.created_at, reverse=True)

    return [ReportThread(head=head,
                         comments=sorted(head.comments.all(), key=lambda c: c.created_at))
            for head in heads]


def get_moderations_by_thread_uuid(threads: list[ReportThread]
                                   ) -> dict[UUID, list[ModerationMixin]]:
    head_uuids = [thread.head.uuid for thread in threads]

    moderations_by_thread_uuid = {}
    for moderation in IssueModeration.objects.filter(issue_id__in=head_uuids):
        moderations_by_thread_uuid.setdefault(moderation.issue_id, []).append(moderation)
    for moderation in ApprovalModeration.objects.filter(approval_id__in=head_uuids):
        moderations_by_thread_uuid.setdefault(moderation.approval_id, []).append(moderation)

    return moderations_by_thread_uuid


##################
# COUNT & LABELS #
##################

def get_count_and_label(website: Website):
    count_and_label = []
    for count, label, singular_tooltip, plural_tooltip in [
        (len(website.approvals.all()), '👍', 'avis positif', 'avis positifs'),
        (len(website.issues.all()), '👎', 'erreur signalée', 'erreurs signalées'),
    ]:
        if count:
            count_and_label.append({
                'count': count,
                'label': label,
                'tooltip': singular_tooltip if count <= 1 else plural_tooltip
            })

    return count_and_label
