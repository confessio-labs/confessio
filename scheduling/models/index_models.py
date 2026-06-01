from django.contrib.postgres.fields import ArrayField
from django.db import models

from core.models.base_models import TimeStampMixin
from scheduling.workflows.parsing.liturgical import PeriodEnum


class IndexEvent(TimeStampMixin):
    scheduling = models.ForeignKey('scheduling.Scheduling', on_delete=models.CASCADE,
                                   related_name='index_events')
    church = models.ForeignKey('registry.Church', on_delete=models.CASCADE,
                               related_name='index_events')
    day = models.DateField(db_index=True)
    start_time = models.TimeField(db_index=True)
    indexed_end_time = models.TimeField(db_index=True)
    displayed_end_time = models.TimeField(db_index=False, null=True)
    start_tz_datetime = models.DateTimeField(db_index=True)
    indexed_end_tz_datetime = models.DateTimeField(db_index=True)
    schedules_indices = ArrayField(models.SmallIntegerField())
    has_been_moderated = models.BooleanField()
    church_color = models.CharField(max_length=9)
    periods = ArrayField(models.CharField(max_length=16, choices=PeriodEnum.choices),
                         default=list)

    class Meta:
        unique_together = ('church', 'day', 'start_time', 'displayed_end_time')

    def __lt__(self, other: 'IndexEvent'):
        return (self.day, self.start_time, self.church_color) < \
            (other.day, other.start_time, other.church_color)
