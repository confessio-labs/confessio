from abc import abstractmethod

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Count, Q
from django.urls import reverse

from core.models.base_models import TimeStampMixin
from registry.utils.color_utils import get_color_from_string
from registry.models import Diocese


class ModerationStatus(models.TextChoices):
    TO_VALIDATE = 'to_validate'
    VALIDATED = 'validated'
    BUG = 'bug'


class ModerationMixin(TimeStampMixin):
    @property
    @abstractmethod
    def resource(self):
        pass

    status = models.CharField(max_length=12, choices=ModerationStatus)
    comment = models.TextField(null=True, default=None, blank=True)

    @property
    @abstractmethod
    def diocese(self) -> Diocese | None:
        pass

    @diocese.setter
    @abstractmethod
    def diocese(self, diocese: Diocese | None):
        pass

    @property
    @abstractmethod
    def category(self):
        pass

    class Meta:
        abstract = True

    @classmethod
    def get_category_stat(cls, stat, status: str, diocese: Diocese | None, count: int):
        diocese_slug = diocese.slug if diocese else 'no_diocese'

        return {
            'resource': cls.resource,
            'url': reverse('moderate_next_' + str(cls.resource),
                           kwargs={'category': stat['category'], 'status': status,
                                   'diocese_slug': diocese_slug}),
            'category': stat['category'],
            'status': status,
            'total': count,
            'color': get_color_from_string(f"{cls.resource}{stat['category']}"),
        }

    @classmethod
    def get_stats_by_category(cls, diocese: Diocese | None):
        stats = []
        objects_filter = cls.objects.filter(
            status__in=[ModerationStatus.TO_VALIDATE, ModerationStatus.BUG],
        )
        if diocese:
            objects_filter = objects_filter.filter(diocese=diocese)
        query_stats = objects_filter.all()\
            .values('category')\
            .annotate(total_count=Count('category'),
                      bug_count=Count('uuid',
                                      filter=Q(status=ModerationStatus.BUG)))
        for stat in query_stats:
            if stat['bug_count']:
                stats.append(cls.get_category_stat(
                    stat, status=ModerationStatus.BUG,
                    diocese=diocese, count=stat['bug_count']))
            if stat['total_count'] - stat['bug_count']:
                stats.append(cls.get_category_stat(
                    stat, status=ModerationStatus.TO_VALIDATE,
                    diocese=diocese,
                    count=stat['total_count'] - stat['bug_count']))

        return stats

    def save(self, *args, **kwargs):
        if not self.status:
            raise ValueError(
                f"{type(self).__name__} cannot be saved without an explicit status"
            )
        super().save(*args, **kwargs)

    def validate(self, user: User):
        if self.delete_on_validate():
            self.delete()
        else:
            self.status = ModerationStatus.VALIDATED
            self.save()

    @abstractmethod
    def delete_on_validate(self) -> bool:
        pass

    def set_status(self, new_status: str, user: User):
        if new_status == ModerationStatus.VALIDATED:
            self.validate(user)
        else:
            self.status = new_status
            self.save()

    def get_diocese_slug(self) -> str:
        return self.diocese.slug if self.diocese else 'no_diocese'


class ResourceDoesNotExistError(Exception):
    pass
