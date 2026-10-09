from django.db import models
from simple_history.models import HistoricalRecords

from core.models.base_models import BaseComment, BaseUserReport


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
