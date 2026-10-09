from django.db import models
from simple_history.models import HistoricalRecords

from core.models.base_models import BaseComment, BaseUserReport
from registry.models import ModerationMixin


class Issue(BaseUserReport):
    website = models.ForeignKey('registry.Website', on_delete=models.CASCADE,
                                related_name='issues')
    church = models.ForeignKey('registry.Church', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='issues')
    content = models.TextField()
    solved_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords()


class IssueComment(BaseComment):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='comments')


class IssueModeration(ModerationMixin):
    class Category(models.TextChoices):
        NEW_ISSUE = "new_issue"
        NEW_COMMENT = "new_comment"

    resource = 'issue'
    diocese = models.ForeignKey('registry.Diocese', on_delete=models.CASCADE,
                                related_name=f'{resource}_moderations')
    history = HistoricalRecords()
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='moderations')
    category = models.CharField(max_length=16, choices=Category)

    class Meta:
        unique_together = ('issue', 'category')

    def delete_on_validate(self) -> bool:
        # we keep the row, to keep track of which issues have been reviewed
        return False
