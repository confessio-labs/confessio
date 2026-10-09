from django.db import models
from simple_history.models import HistoricalRecords

from core.models.base_models import BaseComment, BaseUserReport
from registry.models import ModerationMixin


class Approval(BaseUserReport):
    website = models.ForeignKey('registry.Website', on_delete=models.CASCADE,
                                related_name='approvals')
    church = models.ForeignKey('registry.Church', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='approvals')
    content = models.TextField(null=True, blank=True)

    history = HistoricalRecords()


class ApprovalComment(BaseComment):
    approval = models.ForeignKey(Approval, on_delete=models.CASCADE, related_name='comments')


class ApprovalModeration(ModerationMixin):
    class Category(models.TextChoices):
        NEW_APPROVAL = "new_approval"
        NEW_COMMENT = "new_comment"

    resource = 'approval'
    diocese = models.ForeignKey('registry.Diocese', on_delete=models.CASCADE,
                                related_name=f'{resource}_moderations')
    history = HistoricalRecords()
    approval = models.ForeignKey(Approval, on_delete=models.CASCADE, related_name='moderations')
    category = models.CharField(max_length=16, choices=Category)

    class Meta:
        unique_together = ('approval', 'category')

    def delete_on_validate(self) -> bool:
        # we keep the row, to keep track of which approvals have been reviewed
        return False
