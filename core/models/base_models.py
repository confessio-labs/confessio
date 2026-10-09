import uuid

from django.db import models


class TimeStampMixin(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = models.Manager()

    class Meta:
        abstract = True
        get_latest_by = ['updated_at']


class BaseUserReport(TimeStampMixin):
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='+')
    user_agent = models.TextField(null=True, blank=True)
    ip_address_hash = models.CharField(max_length=64, null=True, blank=True)

    class Meta(TimeStampMixin.Meta):
        abstract = True


class BaseComment(BaseUserReport):
    content = models.TextField()

    class Meta(BaseUserReport.Meta):
        abstract = True


class BaseNote(BaseUserReport):
    class Status(models.TextChoices):
        OPEN = "open"
        ACTIVE = "active"
        CENSORED = "censored"

    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    expire_at = models.DateTimeField()

    class Meta(BaseUserReport.Meta):
        abstract = True
