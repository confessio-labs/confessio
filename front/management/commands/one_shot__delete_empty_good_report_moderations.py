from django.db.models import Q

from core.management.abstract_command import AbstractCommand
from front.models import Report, ReportModeration


class Command(AbstractCommand):
    help = "Delete the moderations of the good reports that carry no comment."

    def handle(self, *args, **options):
        # the queryset side of is_empty_good_report: a comment is empty either way
        moderations = ReportModeration.objects.filter(
            Q(report__comment__isnull=True) | Q(report__comment=''),
            report__feedback_type=Report.FeedbackType.GOOD,
        )
        self.info(f'{moderations.count()} moderations on a good report with no comment')

        deleted_count, _ = moderations.delete()
        self.success(f'Deleted {deleted_count} report moderations')
