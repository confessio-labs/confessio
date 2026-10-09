import uuid
from collections import Counter

from django.db import transaction

from core.management.abstract_command import AbstractCommand
from front.models import Approval, ApprovalModeration, Issue, IssueModeration, Report, \
    ReportModeration
from registry.models.base_moderation_models import ModerationStatus

STATUS_PRIORITY = [ModerationStatus.TO_VALIDATE, ModerationStatus.BUG,
                   ModerationStatus.VALIDATED]


class Command(AbstractCommand):
    help = "Rebuild Issue/Approval moderations from the report moderations. Idempotent."

    def handle(self, *args, **options):
        with transaction.atomic():
            IssueModeration.objects.all().delete()
            ApprovalModeration.objects.all().delete()
            self.migrate_moderations()

    def migrate_moderations(self):
        issue_uuids = set(Issue.objects.values_list('uuid', flat=True))
        approval_uuids = set(Approval.objects.values_list('uuid', flat=True))

        # A thread gets one moderation per category: replies all land on the same row
        groups = {}
        unmirrored_count = 0
        report_moderations = ReportModeration.objects\
            .select_related('report__main_report').order_by('updated_at')
        for report_moderation in report_moderations:
            report = report_moderation.report
            head = report.main_report or report
            is_approval = head.feedback_type == Report.FeedbackType.GOOD
            if head.uuid not in (approval_uuids if is_approval else issue_uuids):
                unmirrored_count += 1
                continue

            groups.setdefault((head.uuid, is_approval, report.main_report_id is None), [])\
                .append(report_moderation)

        issue_moderations = []
        approval_moderations = []
        for (thread_uuid, is_approval, is_head), group in groups.items():
            fields = get_merged_fields(group)
            if is_approval:
                category = ApprovalModeration.Category.NEW_APPROVAL if is_head \
                    else ApprovalModeration.Category.NEW_COMMENT
                approval_moderations.append(ApprovalModeration(
                    approval_id=thread_uuid, category=category, **fields))
            else:
                category = IssueModeration.Category.NEW_ISSUE if is_head \
                    else IssueModeration.Category.NEW_COMMENT
                issue_moderations.append(IssueModeration(
                    issue_id=thread_uuid, category=category, **fields))

        if unmirrored_count:
            self.warning(f'{unmirrored_count} report moderations skipped, their thread is not '
                         f'mirrored: run one_shot__migrate_reports_to_issues first')
        self.info(f'{report_moderations.count()} report moderations')
        self.bulk_create_keeping_timestamps(IssueModeration, issue_moderations)
        self.bulk_create_keeping_timestamps(ApprovalModeration, approval_moderations)

    def bulk_create_keeping_timestamps(self, model, objs):
        timestamps = {obj.uuid: (obj.created_at, obj.updated_at) for obj in objs}
        # auto_now_add and auto_now override timestamps on create, but bulk_update skips pre_save
        model.objects.bulk_create(objs, batch_size=1000)
        for obj in objs:
            obj.created_at, obj.updated_at = timestamps[obj.uuid]
        model.objects.bulk_update(objs, ['created_at', 'updated_at'], batch_size=1000)
        status_counts = Counter(obj.status for obj in objs)
        self.success(f'Created {len(objs)} {model.__name__}: {dict(status_counts)}')


def get_merged_fields(report_moderations: list[ReportModeration]) -> dict:
    statuses = {report_moderation.status for report_moderation in report_moderations}
    comments = [report_moderation.comment for report_moderation in report_moderations
                if report_moderation.comment]
    return {
        'uuid': report_moderations[0].uuid if len(report_moderations) == 1 else uuid.uuid4(),
        'status': next(status for status in STATUS_PRIORITY if status in statuses),
        'comment': comments[-1] if comments else None,
        'diocese_id': report_moderations[0].diocese_id,
        'created_at': min(m.created_at for m in report_moderations),
        'updated_at': max(m.updated_at for m in report_moderations),
    }
