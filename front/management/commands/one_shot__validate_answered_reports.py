from core.management.abstract_command import AbstractCommand
from front.models import Report, ReportModeration
from registry.models.base_moderation_models import ModerationStatus


class Command(AbstractCommand):
    help = "Validate the report moderations whose thread already got an answer from an admin."

    def handle(self, *args, **options):
        # An answer is a reply written by a signed-in user, and replies all hang off the
        # thread head, so that is the report they point to.
        answered_thread_uuids = set(
            Report.objects.filter(main_report__isnull=False, user__isnull=False)
                          .values_list('main_report_id', flat=True)
        )
        self.info(f'{len(answered_thread_uuids)} report threads answered by an admin')

        moderations = ReportModeration.objects\
            .filter(status=ModerationStatus.TO_VALIDATE)\
            .select_related('report')\
            .all()

        validated_count = 0
        unanswered_count = 0
        for moderation in moderations:
            report = moderation.report
            thread_uuid = report.main_report_id or report.uuid
            if thread_uuid not in answered_thread_uuids:
                unanswered_count += 1
                continue

            moderation.validate(None)
            validated_count += 1

        self.success(f'Validated {validated_count} report moderations')
        self.info(f'Left {unanswered_count} report moderations to validate, unanswered')
