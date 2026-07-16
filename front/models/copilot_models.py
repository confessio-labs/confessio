from django.db import models

from core.models.base_models import TimeStampMixin


class CopilotDiscussion(TimeStampMixin):
    class Status(models.TextChoices):
        IDLE = "idle"
        RUNNING = "running"
        AWAITING_APPROVAL = "awaiting_approval"
        ERROR = "error"

    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True,
                             related_name='copilot_discussions')
    title = models.CharField(max_length=255, blank=True)
    website = models.ForeignKey('registry.Website', on_delete=models.SET_NULL, null=True,
                                blank=True, related_name='copilot_discussions')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IDLE)
    # Write-through cache of the native PydanticAI message history (ModelMessagesTypeAdapter),
    # refreshed on every finalize. A new turn's context is rebuilt from the CopilotDiscussionItem
    # rows (the durable source of truth); this cache is read back only on the approval-resume path,
    # which needs a freshly-finalized native history to resume the deferred tool calls.
    pydantic_messages = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True)

    def __str__(self):
        return self.title or str(self.uuid)


class CopilotDiscussionItem(TimeStampMixin):
    class ItemType(models.TextChoices):
        USER_MESSAGE = "user_message"
        AGENT_MESSAGE = "agent_message"
        AUTONOMOUS_TOOL_CALL = "autonomous_tool_call"
        PROPOSED_TOOL_CALL = "proposed_tool_call"

    class ApprovalStatus(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"
        FAILURE = "failure"

    discussion = models.ForeignKey(CopilotDiscussion, on_delete=models.CASCADE,
                                   related_name='items')
    # Monotonic order within a discussion; also the polling cursor (?since=<position>).
    position = models.PositiveIntegerField()
    item_type = models.CharField(max_length=30, choices=ItemType.choices)
    text = models.TextField(blank=True)
    tool_name = models.CharField(max_length=100, blank=True)
    tool_args = models.JSONField(null=True, blank=True)
    tool_result = models.JSONField(null=True, blank=True)
    # PydanticAI tool call id, used to remap an approval into DeferredToolResults on resume.
    tool_call_id = models.CharField(max_length=100, blank=True)
    approval_status = models.CharField(max_length=10, choices=ApprovalStatus.choices, blank=True)

    class Meta:
        ordering = ['position']
        unique_together = ('discussion', 'position')

    def __str__(self):
        return f'{self.discussion_id} #{self.position} {self.item_type}'
