from django.contrib import admin
from django.contrib.admin import ModelAdmin

from front.models import Approval, ApprovalComment, Conversation, CopilotDiscussion, Issue, \
    IssueComment


class IssueCommentInline(admin.TabularInline):
    model = IssueComment
    fields = ['content', 'user', 'created_at']
    readonly_fields = ['user', 'created_at']
    extra = 0


@admin.register(Issue)
class IssueAdmin(ModelAdmin):
    list_display = ['content', 'website', 'solved_at', 'created_at']
    fields = ['content', 'website', 'church', 'solved_at', 'user', 'created_at']
    readonly_fields = ['website', 'church', 'user', 'created_at']
    inlines = [IssueCommentInline]


class ApprovalCommentInline(admin.TabularInline):
    model = ApprovalComment
    fields = ['content', 'user', 'created_at']
    readonly_fields = ['user', 'created_at']
    extra = 0


@admin.register(Approval)
class ApprovalAdmin(ModelAdmin):
    list_display = ['content', 'website', 'created_at']
    fields = ['content', 'website', 'church', 'user', 'created_at']
    readonly_fields = ['website', 'church', 'user', 'created_at']
    inlines = [ApprovalCommentInline]


@admin.register(CopilotDiscussion)
class CopilotDiscussionAdmin(ModelAdmin):
    list_display = ['__str__', 'user', 'website', 'status', 'updated_at']
    list_filter = ['status']


@admin.register(Conversation)
class ConversationAdmin(ModelAdmin):
    list_display = ['__str__', 'email', 'subject', 'updated_at']
    search_fields = ['email', 'subject']
