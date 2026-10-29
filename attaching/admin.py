from django.contrib import admin
from django.contrib.admin import ModelAdmin

from attaching.models import FileNote, FileNoteComment, TextNote, TextNoteComment


class FileNoteCommentInline(admin.TabularInline):
    model = FileNoteComment
    fields = ['content', 'user', 'created_at']
    readonly_fields = ['user', 'created_at']
    extra = 0


@admin.register(FileNote)
class FileNoteAdmin(ModelAdmin):
    list_display = ['website', 'name', 'caption', 'status', 'expire_at', 'created_at']
    fields = ['name', 'caption', 'email', 'status', 'expire_at', 'human_html', 'llm_html']
    readonly_fields = ['email']
    inlines = [FileNoteCommentInline]


class TextNoteCommentInline(admin.TabularInline):
    model = TextNoteComment
    fields = ['content', 'user', 'created_at']
    readonly_fields = ['user', 'created_at']
    extra = 0


@admin.register(TextNote)
class TextNoteAdmin(ModelAdmin):
    list_display = ['website', 'content', 'status', 'expire_at', 'created_at']
    fields = ['content', 'email', 'status', 'expire_at']
    readonly_fields = ['email']
    inlines = [TextNoteCommentInline]
