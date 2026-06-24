from datetime import date
from typing import Optional

from django.template.defaulttags import register
from django.urls import reverse

from crawling.models import CrawlingModeration
from fetching.models import OClocherOrganizationModeration, OClocherMatchingModeration
from front.models import ReportModeration
from front.services.card.website_events_service import WebsiteEvents
from front.services.card.website_schedules_service import WebsiteSchedules
from registry.models import WebsiteModeration, ChurchModeration, ParishModeration, \
    ModerationMixin, Diocese, Website
from registry.models.base_moderation_models import ModerationStatus
from scheduling.models import ParsingModeration, SchedulingModeration, \
    ValidatedSchedulesModeration, ValidatedSchedules
from scheduling.models.pruning_models import Pruning, PruningModeration, SentenceModeration
from scheduling.public_model import BaseSource
from scheduling.utils.list_utils import enumerate_with_and


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter
def get_item_str(dictionary, key):
    return dictionary.get(str(key))


@register.filter
def days_of_range(website_events: WebsiteEvents,
                  range_number_as_str: str) -> list[date]:
    sorted_days = sorted(website_events.index_events_by_day.keys())
    nb_days = 4
    range_number = int(range_number_as_str) - 1

    return sorted_days[range_number * nb_days:(range_number + 1) * nb_days]


@register.filter
def subtract(v1, v2):
    return v1 - v2


@register.filter
def get_ith(some_list: list, i):
    return some_list[i]


@register.filter
def negate(value):
    return not value


@register.filter
def has_relation_text(website_schedules: WebsiteSchedules | None) -> str:
    if not website_schedules:
        return ''

    relations = []
    if website_schedules.sourced_schedules_list.is_related_to_mass_sources:
        relations.append('messes')
    if website_schedules.sourced_schedules_list.is_related_to_adoration_sources:
        relations.append('adorations')
    if website_schedules.sourced_schedules_list.is_related_to_permanence_sources:
        relations.append('permanences')

    if relations:
        relation_text = enumerate_with_and(relations)

        return f'👉 Certains horaires sont liés aux {relation_text}'

    return ''


@register.filter
def relation_sources(website_schedules: WebsiteSchedules | None
                     ) -> list[BaseSource]:
    if not website_schedules:
        return []

    return list(set(website_schedules.sourced_schedules_list.is_related_to_mass_sources
                    + website_schedules.sourced_schedules_list.is_related_to_adoration_sources
                    + website_schedules.sourced_schedules_list.is_related_to_permanence_sources))


@register.filter
def has_validated_schedules(website: Website) -> bool:
    try:
        validated_schedules = website.validated_schedules
        return validated_schedules is not None
    except ValidatedSchedules.DoesNotExist:
        return False


@register.filter
def get_url(moderation: ModerationMixin):
    return reverse(f'moderate_one_' + moderation.resource,
                   kwargs={
                       'category': moderation.category,
                       'status': moderation.status,
                       'moderation_uuid': moderation.uuid,
                       'diocese_slug': moderation.get_diocese_slug(),
                   })


@register.filter
def get_unvalidated_pruning_moderation(pruning: Pruning) -> Optional[PruningModeration]:
    try:
        return pruning.moderations.exclude(
            status=ModerationStatus.VALIDATED,
        ).filter(
            category=PruningModeration.Category.NEW_PRUNED_HTML,
        ).get()
    except PruningModeration.DoesNotExist:
        return None


@register.simple_tag
def get_dioceses() -> list[Diocese | None]:
    return [None] + list(Diocese.objects.all())


@register.filter
def get_moderation_stats(diocese: Diocese | None):
    return sum([
        WebsiteModeration.get_stats_by_category(diocese),
        ParishModeration.get_stats_by_category(diocese),
        ChurchModeration.get_stats_by_category(diocese),
        PruningModeration.get_stats_by_category(diocese),
        SentenceModeration.get_stats_by_category(diocese),
        ParsingModeration.get_stats_by_category(diocese),
        ReportModeration.get_stats_by_category(diocese),
        CrawlingModeration.get_stats_by_category(diocese),
        SchedulingModeration.get_stats_by_category(diocese),
        ValidatedSchedulesModeration.get_stats_by_category(diocese),
        OClocherOrganizationModeration.get_stats_by_category(diocese),
        OClocherMatchingModeration.get_stats_by_category(diocese),
    ], [])


@register.simple_tag
def countdown_july_15():
    today = date.today()

    target = date(today.year, 7, 15)
    if today > target:
        target = date(today.year + 1, 7, 15)

    return f"J-{(target - today).days}"
