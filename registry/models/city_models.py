from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.indexes import GinIndex, GistIndex
from django.db import models
from django.db.models import Value
from django.db.models.functions import Lower, Replace

from core.models.base_models import TimeStampMixin
from core.models.db_functions import ImmutableUnaccent


class City(TimeStampMixin):
    """French commune, seeded from geo.api.gouv.fr by `one_shot__seed_cities`.

    Deliberately has no HistoricalRecords: the table is bulk-refreshed from an external dump,
    and simple_history can not mirror a GeneratedField.
    """
    insee_code = models.CharField(max_length=5, unique=True)
    name = models.CharField(max_length=255)
    # Filled by `generate_city_slugs`. unique + null is exactly "unique if not null" on Postgres:
    # two NULLs are never equal in a unique index.
    slug = models.SlugField(max_length=100, unique=True, null=True, blank=True)
    zipcode = models.CharField(max_length=5)
    population = models.PositiveIntegerField(default=0)
    location = gis_models.PointField(geography=False, srid=4326)
    # Keep in sync with registry.utils.city_name_utils.normalize_city_name
    name_norm = models.GeneratedField(
        expression=Replace(
            Replace(Lower(ImmutableUnaccent('name')), Value('-'), Value(' ')),
            Value("'"), Value(' '),
        ),
        output_field=models.TextField(),
        db_persist=True,
    )

    class Meta:
        indexes = [
            GistIndex(fields=['location']),
            GinIndex(name='city_name_norm_trgm', fields=['name_norm'],
                     opclasses=['gin_trgm_ops']),
        ]

    def __str__(self):
        return f'{self.name} ({self.zipcode})'
