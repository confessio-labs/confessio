from django.db import models
from simple_history.models import HistoricalRecords

from core.models.base_models import BaseComment, BaseUserReport


class Approval(BaseUserReport):
    website = models.ForeignKey('registry.Website', on_delete=models.CASCADE,
                                related_name='approvals')
    church = models.ForeignKey('registry.Church', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='approvals')
    content = models.TextField(null=True, blank=True)

    history = HistoricalRecords()


class ApprovalComment(BaseComment):
    approval = models.ForeignKey(Approval, on_delete=models.CASCADE, related_name='comments')
