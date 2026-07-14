from django.db import models
from simple_history.models import HistoricalRecords

from core.models.base_models import TimeStampMixin
from registry.models import ModerationMixin


class Report(TimeStampMixin):
    website = models.ForeignKey('registry.Website', on_delete=models.CASCADE,
                                related_name='reports')
    church = models.ForeignKey('registry.Church', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='reports')

    class FeedbackType(models.TextChoices):
        GOOD = "good"
        ERROR = "error"
        COMMENT = "comment"

    class ErrorType(models.TextChoices):
        OUTDATED = "outdated"
        CHURCHES = "churches"
        PARAGRAPHS = "paragraphs"
        SCHEDULES = "schedules"

    feedback_type = models.CharField(max_length=8, choices=FeedbackType.choices)
    error_type = models.CharField(max_length=10, choices=ErrorType.choices, null=True, blank=True)
    main_report = models.ForeignKey('Report', on_delete=models.CASCADE, null=True, blank=True)

    comment = models.TextField(null=True)
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)
    user_agent = models.TextField(null=True)
    ip_address_hash = models.CharField(max_length=64, null=True)


class ReportModeration(ModerationMixin):
    class Category(models.TextChoices):
        GOOD = "good"
        ERROR = "error"
        COMMENT = "comment"

    resource = 'report'
    diocese = models.ForeignKey('registry.Diocese', on_delete=models.CASCADE,
                                related_name=f'{resource}_moderations')
    history = HistoricalRecords()
    report = models.ForeignKey('Report', on_delete=models.CASCADE, related_name='moderations')
    category = models.CharField(max_length=16, choices=Category)

    class Meta:
        unique_together = ('report', 'category')

    def delete_on_validate(self) -> bool:
        # we don't need to keep validated ReportModeration
        return True
