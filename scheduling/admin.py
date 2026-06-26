from django.contrib import admin
from django.contrib.admin import ModelAdmin

from scheduling.models.pruning_models import Classifier, Encoder, Sentence


@admin.register(Encoder)
class EncoderAdmin(ModelAdmin):
    list_display = ["uuid", "status", "base_model", "created_at",
                    "accuracy_temporal", "accuracy_confession", "test_size"]
    ordering = ["-created_at"]
    fields = ["status", "base_model", "hf_repo_id", "hf_revision", "dimensions",
              "accuracy_temporal", "accuracy_confession", "test_size", "notes"]
    readonly_fields = ["base_model", "hf_repo_id", "hf_revision", "dimensions",
                       "accuracy_temporal", "accuracy_confession", "test_size"]


@admin.register(Classifier)
class ClassifierAdmin(ModelAdmin):
    list_display = ["uuid", "status", "target", "created_at", "accuracy", 'test_size']
    ordering = ["-created_at"]
    fields = ['status']


@admin.register(Sentence)
class SentenceAdmin(ModelAdmin):
    list_display = ["line", "action", "human_temporal", "human_confession"]
    fields = ["line", 'action', "human_temporal", "human_confession"]
