from django.db import models

from core.models.base_models import TimeStampMixin


class Conversation(TimeStampMixin):
    """An email thread with one external correspondent.

    Its uuid is the thread key: it travels in every outgoing body as a /messaging/<uuid> link,
    and is read back from the quoted text of inbound replies.
    """
    email = models.EmailField()
    name = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=255)

    def __str__(self):
        return f'{self.subject} — {self.email}'


class Message(TimeStampMixin):
    class Direction(models.TextChoices):
        OUTBOUND = "outbound"  # admin -> correspondent
        INBOUND = "inbound"  # correspondent -> admin

    class Status(models.TextChoices):
        RECEIVED = "received"
        SENT = "sent"
        FAILED = "failed"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE,
                                     related_name='messages')
    direction = models.CharField(max_length=10, choices=Direction.choices)
    body = models.TextField()
    # Outbound: the admin who wrote it. Inbound: null.
    author = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='sent_messages')
    # Inbound: the raw From header. It differs from conversation.email on contact-form mails,
    # which we send from no-reply@ with the visitor in Reply-To.
    from_email = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.conversation_id} {self.direction} {self.created_at}'
