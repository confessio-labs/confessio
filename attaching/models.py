from django.db import models
from simple_history.models import HistoricalRecords

from core.models.base_models import TimeStampMixin
from core.utils.llm_utils import LLMProvider


class Image(TimeStampMixin):
    website = models.ForeignKey('registry.Website', on_delete=models.CASCADE, related_name='images')
    name = models.CharField(max_length=256)
    comment = models.TextField(null=True, blank=True)
    llm_html = models.TextField(null=True, blank=True)
    llm_provider = models.CharField(choices=LLMProvider.choices(), null=True, blank=True)
    llm_model = models.CharField(max_length=100, null=True, blank=True)
    prompt_hash = models.CharField(max_length=32, null=True, blank=True)
    llm_error_detail = models.TextField(null=True, blank=True)
    human_html = models.TextField(null=True, blank=True)
    prunings = models.ManyToManyField('scheduling.Pruning', related_name='images')
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)
    user_agent = models.TextField(null=True, blank=True)
    ip_address_hash = models.CharField(max_length=64, null=True, blank=True)

    history = HistoricalRecords()


class PdfRecognition(TimeStampMixin):
    pdf_url = models.URLField(max_length=300)
    pdf_sha256 = models.CharField(max_length=64, unique=True)
    llm_html = models.TextField(null=True, blank=True)
    llm_provider = models.CharField(choices=LLMProvider.choices(), null=True, blank=True)
    llm_model = models.CharField(max_length=100, null=True, blank=True)
    prompt_hash = models.CharField(max_length=32, null=True, blank=True)
    llm_error_detail = models.TextField(null=True, blank=True)
