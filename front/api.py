from datetime import datetime
from uuid import UUID

from django.db.models import Exists, OuterRef
from ninja import NinjaAPI, Schema, Field

from registry.models import Church, ChurchModeration, Parish, Website
from registry.models.base_moderation_models import ModerationStatus
from scheduling.models import Scheduling, IndexEvent
from scheduling.public_model import SourcedScheduleItem
from scheduling.public_service import scheduling_retrieve_scheduling_elements

api = NinjaAPI(urls_namespace='main_api')


############
# CHURCHES #
############

class ChurchOut(Schema):
    uuid: UUID
    name: str
    latitude: float
    longitude: float
    address: str | None
    zipcode: str | None
    city: str | None
    messesinfo_id: str | None
    wikidata_id: str | None
    trouverunemesse_id: UUID | None
    trouverunemesse_slug: str | None
    annuairecatholique_id: UUID | None
    annuairecatholique_business_id: str | None
    parish_uuid: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
    has_validated_moderation: bool = Field(
        description="whether it has been moderated by a human"
    )
    has_unvalidated_moderation: bool = Field(
        description="whether there is pending moderation for human"
    )

    @classmethod
    def from_church(cls, church: Church):
        return cls(
            uuid=church.uuid,
            name=church.name,
            latitude=church.location.y,
            longitude=church.location.x,
            address=church.address,
            zipcode=church.zipcode,
            city=church.city,
            messesinfo_id=church.messesinfo_id,
            wikidata_id=church.wikidata_id,
            trouverunemesse_id=church.trouverunemesse_id,
            trouverunemesse_slug=church.trouverunemesse_slug,
            annuairecatholique_id=church.annuairecatholique_id,
            annuairecatholique_business_id=church.annuairecatholique_business_id,
            parish_uuid=church.parish_id,
            is_active=church.is_active,
            created_at=church.created_at,
            updated_at=church.updated_at,
            has_validated_moderation=church.has_validated_moderation,
            has_unvalidated_moderation=church.has_unvalidated_moderation,
        )


@api.get("/churches", response=list[ChurchOut])
def api_public_churches(request, limit: int = 10, offset: int = 0, updated_from: datetime = None
                        ) -> list[ChurchOut]:
    limit = max(0, min(100, limit))
    offset = max(0, offset)

    church_query = Church.objects.annotate(
        has_validated_moderation=Exists(
            ChurchModeration.history.filter(church=OuterRef('pk'), history_user_id__isnull=False)
        ),
        has_unvalidated_moderation=Exists(
            ChurchModeration.objects.filter(
                church=OuterRef('pk'),
            ).exclude(status=ModerationStatus.VALIDATED)
        ),
    )
    if updated_from:
        church_query = church_query.filter(updated_at__gte=updated_from)
    churches = church_query.order_by('updated_at').all()[offset:offset + limit]

    return list(map(ChurchOut.from_church, churches))


############
# PARISHES #
############

class ParishOut(Schema):
    uuid: UUID
    name: str
    messesinfo_id: str | None
    website_uuid: UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_parish(cls, parish: Parish):
        return cls(
            uuid=parish.uuid,
            name=parish.name,
            messesinfo_id=parish.messesinfo_community_id,
            website_uuid=parish.website.uuid if parish.website else None,
            created_at=parish.created_at,
            updated_at=parish.updated_at,
        )


@api.get("/parishes", response=list[ParishOut])
def api_public_parishes(request, limit: int = 10, offset: int = 0, updated_from: datetime = None
                        ) -> list[ParishOut]:
    limit = max(0, min(100, limit))
    offset = max(0, offset)

    parish_query = Parish.objects
    if updated_from:
        parish_query = parish_query.filter(updated_at__gte=updated_from)
    parishes = parish_query.order_by('updated_at').all()[offset:offset + limit]

    return list(map(ParishOut.from_parish, parishes))


############
# WEBSITES #
############

class WebsiteOut(Schema):
    uuid: UUID
    name: str
    home_url: str
    created_at: datetime
    updated_at: datetime
    contact_emails: list[str]

    @classmethod
    def from_website(cls, website: Website):
        return cls(
            uuid=website.uuid,
            name=website.name,
            home_url=website.home_url,
            created_at=website.created_at,
            updated_at=website.updated_at,
            contact_emails=website.contact_emails or [],
        )


@api.get("/websites", response=list[WebsiteOut])
def api_public_websites(request, limit: int = 10, offset: int = 0, updated_from: datetime = None
                        ) -> list[WebsiteOut]:
    limit = max(0, min(100, limit))
    offset = max(0, offset)

    website_query = Website.objects
    if updated_from:
        website_query = website_query.filter(updated_at__gte=updated_from)
    websites = website_query.order_by('updated_at').all()[offset:offset + limit]

    return list(map(WebsiteOut.from_website, websites))


###############
# SCHEDULINGS #
###############

class ScheduleOut(Schema):
    explanation: str

    @classmethod
    def from_sourced_schedule_item(cls, sourced_schedule_item: SourcedScheduleItem
                                   ) -> 'ScheduleOut':
        return cls(
            explanation=sourced_schedule_item.explanation,
        )


class SchedulesByChurchOut(Schema):
    church_uuid: UUID
    schedules: list[ScheduleOut]

    @classmethod
    def from_sourced_schedule_item(cls, church_uuid: UUID,
                                   sourced_schedules: list[SourcedScheduleItem]
                                   ) -> 'SchedulesByChurchOut':
        return cls(
            church_uuid=church_uuid,
            schedules=list(map(ScheduleOut.from_sourced_schedule_item, sourced_schedules)),
        )


class EventOut(Schema):
    start: datetime
    end: datetime | None

    @classmethod
    def from_index_event(cls, index_event: IndexEvent) -> 'EventOut':
        start = datetime.combine(index_event.day, index_event.start_time)
        end = datetime.combine(index_event.day, index_event.displayed_end_time) \
            if index_event.displayed_end_time else None

        return cls(
            start=start,
            end=end,
        )


class EventsByChurchOut(Schema):
    church_uuid: UUID
    events: list[EventOut]

    @classmethod
    def from_index_events(cls, church_uuid: UUID,
                          index_events: list[IndexEvent]) -> 'EventsByChurchOut':
        return cls(
            church_uuid=church_uuid,
            events=list(map(EventOut.from_index_event, index_events)),
        )


class SchedulingOut(Schema):
    uuid: UUID
    created_at: datetime
    updated_at: datetime
    website_uuid: UUID
    schedules_by_churches: list[SchedulesByChurchOut]
    events_by_churches: list[EventsByChurchOut]

    @classmethod
    def from_scheduling(cls, scheduling: Scheduling):
        # Events
        index_events_by_church_uuid = {}
        for index_event in scheduling.index_events.all():
            index_events_by_church_uuid.setdefault(index_event.church_id, []).append(index_event)

        events_by_churches = []
        for church_uuid, index_events in index_events_by_church_uuid.items():
            events_by_churches.append(
                EventsByChurchOut.from_index_events(church_uuid, index_events)
            )

        # Schedules
        schedules_by_churches = []
        scheduling_elements = scheduling_retrieve_scheduling_elements(scheduling)
        for schedules_of_church in scheduling_elements.sourced_schedules_list\
                .sourced_schedules_of_churches:
            church = scheduling_elements.church_by_id.get(schedules_of_church.church_id, None)
            if church is None:
                continue

            if not schedules_of_church.sourced_schedules:
                continue

            schedules_by_churches.append(
                SchedulesByChurchOut.from_sourced_schedule_item(
                    church.uuid, schedules_of_church.sourced_schedules)
            )

        return cls(
            uuid=scheduling.uuid,
            created_at=scheduling.created_at,
            updated_at=scheduling.updated_at,
            website_uuid=scheduling.website_id,
            schedules_by_churches=schedules_by_churches,
            events_by_churches=events_by_churches,
        )


@api.get("/schedulings", response=list[SchedulingOut])
def api_public_schedulings(request, limit: int = 10, offset: int = 0, updated_from: datetime = None
                           ) -> list[SchedulingOut]:
    limit = max(0, min(100, limit))
    offset = max(0, offset)

    scheduling_query = Scheduling.objects.filter(status=Scheduling.Status.INDEXED)
    if updated_from:
        scheduling_query = scheduling_query.filter(updated_at__gte=updated_from)
    schedulings = scheduling_query.order_by('updated_at').all()[offset:offset + limit]\
        .prefetch_related('index_events')

    return list(map(SchedulingOut.from_scheduling, schedulings))
