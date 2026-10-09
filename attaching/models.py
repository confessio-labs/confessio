from django.db import models
from simple_history.models import HistoricalRecords

from core.models.base_models import BaseComment, BaseNote, TimeStampMixin
from core.utils.llm_utils import LLMProvider
from registry.models import ModerationMixin


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


class TextNote(BaseNote):
    website = models.ForeignKey('registry.Website', on_delete=models.CASCADE,
                                related_name='text_notes')
    church = models.ForeignKey('registry.Church', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='text_notes')
    content = models.TextField()
    prunings = models.ManyToManyField('scheduling.Pruning', related_name='text_notes')

    history = HistoricalRecords()


class TextNoteComment(BaseComment):
    text_note = models.ForeignKey(TextNote, on_delete=models.CASCADE, related_name='comments')


class FileNote(BaseNote):
    website = models.ForeignKey('registry.Website', on_delete=models.CASCADE,
                                related_name='file_notes')
    church = models.ForeignKey('registry.Church', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='file_notes')
    name = models.CharField(max_length=256)
    caption = models.TextField(null=True, blank=True)
    mime_type = models.CharField(max_length=100)
    llm_html = models.TextField(null=True, blank=True)
    llm_provider = models.CharField(choices=LLMProvider.choices(), null=True, blank=True)
    llm_model = models.CharField(max_length=100, null=True, blank=True)
    llm_prompt_hash = models.CharField(max_length=32, null=True, blank=True)
    llm_error_detail = models.TextField(null=True, blank=True)
    human_html = models.TextField(null=True, blank=True)
    prunings = models.ManyToManyField('scheduling.Pruning', related_name='file_notes')

    history = HistoricalRecords()


class FileNoteComment(BaseComment):
    file_note = models.ForeignKey(FileNote, on_delete=models.CASCADE, related_name='comments')


class PdfRecognition(TimeStampMixin):
    pdf_url = models.URLField(max_length=300)
    pdf_sha256 = models.CharField(max_length=64, unique=True)
    llm_html = models.TextField(null=True, blank=True)
    llm_provider = models.CharField(choices=LLMProvider.choices(), null=True, blank=True)
    llm_model = models.CharField(max_length=100, null=True, blank=True)
    prompt_hash = models.CharField(max_length=32, null=True, blank=True)
    llm_error_detail = models.TextField(null=True, blank=True)
    pdf_size = models.PositiveIntegerField(null=True, blank=True)
    nb_pages = models.PositiveIntegerField(null=True, blank=True)


class ImageModeration(ModerationMixin):
    class Category(models.TextChoices):
        NEW_IMAGE = "new_image"

    resource = 'image'
    diocese = models.ForeignKey('registry.Diocese', on_delete=models.CASCADE,
                                related_name=f'{resource}_moderations', null=True)
    history = HistoricalRecords()
    image = models.ForeignKey(Image, on_delete=models.CASCADE, related_name='moderations')
    category = models.CharField(max_length=16, choices=Category)

    class Meta:
        unique_together = ('image', 'category')

    def delete_on_validate(self) -> bool:
        # we keep the row, to keep track of which images have been reviewed
        return False
