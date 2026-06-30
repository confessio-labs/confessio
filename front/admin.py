from django.contrib import admin
from django.contrib.admin import ModelAdmin

from front.models import CopilotDiscussion, Report


@admin.register(Report)
class ReportAdmin(ModelAdmin):
    list_display = ['comment', 'feedback_type', 'error_type', 'created_at']
    fields = ['comment', 'feedback_type', 'error_type']


@admin.register(CopilotDiscussion)
class CopilotDiscussionAdmin(ModelAdmin):
    list_display = ['__str__', 'user', 'website', 'status', 'updated_at']
    list_filter = ['status']
