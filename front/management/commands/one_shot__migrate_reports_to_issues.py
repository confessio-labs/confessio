from django.db import transaction

from core.management.abstract_command import AbstractCommand
from front.models import Approval, ApprovalComment, Issue, IssueComment, Report


class Command(AbstractCommand):
    help = "Backfill Issue/Approval and their comments from the reports predating double write."

    def handle(self, *args, **options):
        with transaction.atomic():
            self.migrate_heads()
            self.migrate_replies()
        self.check_counts()

    def migrate_heads(self):
        mirrored_uuids = set(Issue.objects.values_list('uuid', flat=True)) \
            | set(Approval.objects.values_list('uuid', flat=True))
        heads = Report.objects.filter(main_report__isnull=True).exclude(uuid__in=mirrored_uuids)

        approvals = []
        issues = []
        for report in heads:
            user_fields = get_user_fields(report)
            if report.feedback_type == Report.FeedbackType.GOOD:
                approvals.append(Approval(website_id=report.website_id,
                                          church_id=report.church_id,
                                          content=report.comment, **user_fields))
            else:
                issues.append(Issue(website_id=report.website_id, church_id=report.church_id,
                                    content=report.comment or '', **user_fields))

        self.info(f'{len(mirrored_uuids)} report heads already mirrored')
        self.bulk_create_keeping_timestamps(Approval, approvals)
        self.bulk_create_keeping_timestamps(Issue, issues)

    def migrate_replies(self):
        mirrored_uuids = set(IssueComment.objects.values_list('uuid', flat=True)) \
            | set(ApprovalComment.objects.values_list('uuid', flat=True))
        replies = Report.objects.filter(main_report__isnull=False)\
            .exclude(uuid__in=mirrored_uuids)\
            .select_related('main_report')

        approval_comments = []
        issue_comments = []
        for report in replies:
            user_fields = get_user_fields(report)
            content = report.comment or ''
            if report.main_report.feedback_type == Report.FeedbackType.GOOD:
                approval_comments.append(ApprovalComment(approval_id=report.main_report_id,
                                                         content=content, **user_fields))
            else:
                issue_comments.append(IssueComment(issue_id=report.main_report_id,
                                                   content=content, **user_fields))

        self.info(f'{len(mirrored_uuids)} report replies already mirrored')
        self.bulk_create_keeping_timestamps(ApprovalComment, approval_comments)
        self.bulk_create_keeping_timestamps(IssueComment, issue_comments)

    def bulk_create_keeping_timestamps(self, model, objs):
        timestamps = {obj.uuid: (obj.created_at, obj.updated_at) for obj in objs}
        # auto_now_add and auto_now override timestamps on create, but bulk_update skips pre_save
        model.objects.bulk_create(objs, batch_size=1000)
        for obj in objs:
            obj.created_at, obj.updated_at = timestamps[obj.uuid]
        model.objects.bulk_update(objs, ['created_at', 'updated_at'], batch_size=1000)
        self.success(f'Created {len(objs)} {model.__name__}')

    def check_counts(self):
        head_uuids = Report.objects.filter(main_report__isnull=True).values('uuid')
        heads_count = head_uuids.count()
        mirrored_heads_count = Issue.objects.filter(uuid__in=head_uuids).count() \
            + Approval.objects.filter(uuid__in=head_uuids).count()
        self.log_count_check('heads', heads_count, mirrored_heads_count)

        reply_uuids = Report.objects.filter(main_report__isnull=False).values('uuid')
        replies_count = reply_uuids.count()
        mirrored_replies_count = IssueComment.objects.filter(uuid__in=reply_uuids).count() \
            + ApprovalComment.objects.filter(uuid__in=reply_uuids).count()
        self.log_count_check('replies', replies_count, mirrored_replies_count)

    def log_count_check(self, label, reports_count, mirrored_count):
        if reports_count == mirrored_count:
            self.success(f'All {reports_count} report {label} are mirrored')
        else:
            self.warning(f'{mirrored_count} report {label} mirrored out of {reports_count}')


def get_user_fields(report: Report) -> dict:
    return {
        'uuid': report.uuid,
        'created_at': report.created_at,
        'updated_at': report.updated_at,
        'user_id': report.user_id,
        'user_agent': report.user_agent,
        'ip_address_hash': report.ip_address_hash,
    }
