from uuid import UUID

from front.services.card.church_color_service import get_church_color_by_uuid
from registry.models import Church
from scheduling.public_model import SourcedSchedulesList


def front_get_church_color_by_uuid(sourced_schedules_list: SourcedSchedulesList,
                                   church_by_id: dict[int, Church]) -> dict[UUID, str]:
    return get_church_color_by_uuid(sourced_schedules_list, church_by_id)
