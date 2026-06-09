from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GistIndex
from django.db import models
from simple_history.models import HistoricalRecords

from core.models.base_models import TimeStampMixin


class Diocese(TimeStampMixin):
    name = models.CharField(max_length=100, unique=True)
    slug = models.CharField(max_length=100, unique=True)
    messesinfo_network_id = models.CharField(max_length=100, unique=True)
    home_url = models.URLField(unique=True, null=True, blank=True)
    history = HistoricalRecords()


class Website(TimeStampMixin):
    class UnreliabilityReason(models.TextChoices):
        SCHEDULE_IN_IMAGE = "schedule_in_image"
        SCHEDULE_IN_PDF = "schedule_in_pdf"
        JAVASCRIPT_REQUIRED = "javascript_required"
        TOO_NOISY_HTML = "too_noisy_html"
        NOT_RESPONDING_AT_ALL = "not_responding_at_all"
        NOT_RESPONDING_IN_TIME = "not_responding_in_time"
        NOT_RESPONDING_200 = "not_responding_200"
        FOREIGN_LANGUAGE = "foreign_language"

    name = models.CharField(max_length=300)
    home_url = models.URLField(unique=True, max_length=255)
    is_active = models.BooleanField(default=True)
    enabled_for_crawling = models.BooleanField(default=True)
    pruning_validation_counter = models.SmallIntegerField(default=0)
    pruning_last_validated_at = models.DateTimeField(null=True, blank=True)
    unreliability_reason = models.CharField(choices=UnreliabilityReason, null=True, blank=True)
    nb_recent_hits = models.PositiveSmallIntegerField(default=0)
    is_best_diocese_hit = models.BooleanField(default=False)
    contact_emails = ArrayField(models.CharField(max_length=100), null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    def delete_if_no_parish(self):
        if not self.parishes.exists():
            self.delete()

    def get_churches(self) -> list['Church']:
        churches = []
        for parish in self.parishes.all():
            churches.extend(parish.churches.all())

        return churches

    def get_diocese(self) -> Diocese | None:
        if not self.parishes.exists():
            return None

        return self.parishes.first().diocese


class Parish(TimeStampMixin):
    name = models.CharField(max_length=100)
    messesinfo_network_id = models.CharField(max_length=100, null=True, blank=True)
    messesinfo_community_id = models.CharField(max_length=200, null=True, unique=True, blank=True)
    website = models.ForeignKey('Website', on_delete=models.CASCADE, related_name='parishes',
                                null=True, blank=True)
    diocese = models.ForeignKey('Diocese', on_delete=models.CASCADE, related_name='parishes')
    history = HistoricalRecords()

    def __str__(self):
        return self.name


class Church(TimeStampMixin):
    name = models.CharField(max_length=120)
    location = gis_models.PointField(geography=False, null=True, srid=4326)
    address = models.CharField(max_length=100, null=True, blank=True)
    zipcode = models.CharField(max_length=5, null=True)
    city = models.CharField(max_length=50, null=True)
    messesinfo_id = models.CharField(max_length=100, null=True, unique=True, blank=True)
    wikidata_id = models.CharField(max_length=100, null=True, unique=True, blank=True)
    trouverunemesse_id = models.UUIDField(null=True, unique=True, blank=True)
    trouverunemesse_slug = models.CharField(max_length=200, null=True, unique=True, blank=True)
    trouverunemesse_updated_at = models.DateTimeField(null=True, blank=True)
    annuairecatholique_id = models.UUIDField(null=True, unique=True, blank=True)
    annuairecatholique_business_id = models.CharField(max_length=50, null=True, blank=True)
    annuairecatholique_updated_at = models.DateTimeField(null=True, blank=True)
    oclocher_id = models.CharField(max_length=32, null=True, unique=True, blank=True)
    parish = models.ForeignKey('Parish', on_delete=models.CASCADE,
                               related_name='churches')
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        indexes = [
            GistIndex(fields=['location']),
        ]

    def get_desc(self) -> str:
        return f'{self.name} {self.city}'
