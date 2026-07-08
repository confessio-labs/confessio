from django.db import models
from simple_history.models import HistoricalRecords

from core.models.base_models import TimeStampMixin
from crawling.utils.url_utils import MAX_URL_LENGTH
from registry.models import ModerationMixin


class Scraping(TimeStampMixin):
    url = models.URLField(max_length=MAX_URL_LENGTH)
    website = models.ForeignKey('registry.Website', on_delete=models.CASCADE,
                                related_name='scrapings')
    prunings = models.ManyToManyField('scheduling.Pruning', related_name='scrapings')

    history = HistoricalRecords()

    class Meta:
        unique_together = ('url', 'website')


class WebsiteForbiddenPath(TimeStampMixin):
    website = models.ForeignKey('registry.Website', on_delete=models.CASCADE,
                                related_name='forbidden_paths')
    path = models.CharField(max_length=MAX_URL_LENGTH)

    class Meta:
        unique_together = ('website', 'path')


class Log(TimeStampMixin):
    class Type(models.TextChoices):
        CRAWLING = "crawling"
        SCRAPING = "scraping"

    class Status(models.TextChoices):
        DONE = "done"
        TIMEOUT = "timeout"
        FAILURE = "failure"

    started_at = models.DateTimeField(null=True)  # TODO make not null
    end_at = models.DateTimeField(null=True)  # TODO make not null
    website = models.ForeignKey('registry.Website', on_delete=models.CASCADE,
                                related_name='crawling_logs')
    content = models.TextField()
    type = models.CharField(max_length=8, choices=Type)
    status = models.CharField(max_length=8, choices=Status)
    error_detail = models.TextField(null=True, blank=True)
    nb_visited_links = models.PositiveSmallIntegerField(null=True, blank=True)
    nb_success_links = models.PositiveSmallIntegerField(null=True, blank=True)


class CrawlingModeration(ModerationMixin):
    class Category(models.TextChoices):
        NO_RESPONSE = "no_resp"
        NO_PAGE = "no_page"
        OK = "ok"

    resource = 'crawling'
    diocese = models.ForeignKey('registry.Diocese', on_delete=models.CASCADE,
                                related_name=f'{resource}_moderations')
    history = HistoricalRecords()
    website = models.OneToOneField('registry.Website', on_delete=models.CASCADE,
                                   related_name=f'{resource}_moderation')
    category = models.CharField(max_length=8, choices=Category)

    def delete_on_validate(self) -> bool:
        return False
