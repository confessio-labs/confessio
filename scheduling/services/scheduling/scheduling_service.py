import datetime
from dataclasses import dataclass, field
from uuid import UUID

from django.db.models import Q, Subquery

from attaching.models import Image
from crawling.models import Scraping
from fetching.models import OClocherSchedule, OClocherMatching, OClocherLocation
from registry.models import Website, Church
from scheduling.models import ParsingModeration, Parsing, IndexEvent
from scheduling.models import Scheduling, SchedulingHistoricalOClocherMatching
from scheduling.models.pruning_models import Pruning
from scheduling.public_model import SourcedSchedulesList
from scheduling.utils.hash_utils import hash_string_to_hex


def get_indexed_scheduling(website: Website) -> Scheduling | None:
    return website.schedulings.filter(status=Scheduling.Status.INDEXED).first()


##########################
# GET SCHEDULING SOURCES #
##########################

@dataclass
class SchedulingSources:
    churches: list[Church] = field(default_factory=list)
    parsings: list[Parsing] = field(default_factory=list)
    oclocher_locations: list[OClocherLocation] = field(default_factory=list)
    oclocher_schedules: list[OClocherSchedule] = field(default_factory=list)
    oclocher_matching: OClocherMatching | None = None


def get_scheduling_sources(scheduling: Scheduling | None) -> SchedulingSources:
    if scheduling is None:
        return SchedulingSources()

    all_churches = []
    for scheduling_church in scheduling.historical_churches.all():
        church_history_id = scheduling_church.church_history_id
        historical_church = Church.history.get(history_id=church_history_id)
        church = historical_church.instance
        all_churches.append(church)

    all_parsings = []
    for pruning_parsing in scheduling.pruning_parsings.all():
        parsing_history_id = pruning_parsing.parsing_history_id
        historical_parsing = Parsing.history.get(history_id=parsing_history_id)
        parsing = historical_parsing.instance
        # A parsing can be linked to several prunings; keep it once so downstream consumers
        # (source numbering, category source lists, schedule extraction) don't see duplicates.
        if parsing not in all_parsings:
            all_parsings.append(parsing)

    all_oclocher_locations = []
    for scheduling_oclocher_location in scheduling.historical_oclocher_locations.all():
        oclocher_location_history_id = scheduling_oclocher_location.oclocher_location_history_id
        historical_oclocher_location = OClocherLocation.history.get(
            history_id=oclocher_location_history_id)
        oclocher_location = historical_oclocher_location.instance
        all_oclocher_locations.append(oclocher_location)

    all_oclocher_schedules = []
    for scheduling_oclocher_schedule in scheduling.historical_oclocher_schedules.all():
        oclocher_schedule_history_id = scheduling_oclocher_schedule.oclocher_schedule_history_id
        historical_oclocher_schedule = OClocherSchedule.history.get(
            history_id=oclocher_schedule_history_id)
        oclocher_schedule = historical_oclocher_schedule.instance
        all_oclocher_schedules.append(oclocher_schedule)

    try:
        scheduling_oclocher_matching = scheduling.historical_oclocher_matching
        oclocher_matching_history_id = scheduling_oclocher_matching.oclocher_matching_history_id
        historical_oclocher_matching = OClocherMatching.history.get(
            history_id=oclocher_matching_history_id)
        oclocher_matching = historical_oclocher_matching.instance
    except SchedulingHistoricalOClocherMatching.DoesNotExist:
        oclocher_matching = None

    return SchedulingSources(
        churches=all_churches,
        parsings=all_parsings,
        oclocher_locations=all_oclocher_locations,
        oclocher_schedules=all_oclocher_schedules,
        oclocher_matching=oclocher_matching,
    )


##################################
# GET SCHEDULING PRIMARY SOURCES #
##################################

@dataclass
class SchedulingPrimarySources:
    scrapings: list[Scraping] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    prunings_by_scraping_uuid: dict[UUID, list[Pruning]] = field(default_factory=dict)
    prunings_by_image_uuid: dict[UUID, list[Pruning]] = field(default_factory=dict)
    parsing_by_pruning_uuid: dict[UUID, Parsing] = field(default_factory=dict)


def get_pruning_by_history_id(pruning_history_id: int,
                              pruning_by_history_id: dict[int, Pruning]) -> Pruning:
    if pruning_history_id in pruning_by_history_id:
        return pruning_by_history_id[pruning_history_id]

    historical_pruning = Pruning.history.get(history_id=pruning_history_id)
    pruning = historical_pruning.instance
    pruning_by_history_id[pruning_history_id] = pruning
    return pruning


def get_scheduling_primary_sources(scheduling: Scheduling | None
                                   ) -> SchedulingPrimarySources:
    if scheduling is None:
        return SchedulingPrimarySources()

    pruning_by_history_id = {}

    parsing_by_pruning_uuid = {}
    for pruning_parsing in scheduling.pruning_parsings.all():
        parsing_history_id = pruning_parsing.parsing_history_id
        historical_parsing = Parsing.history.get(history_id=parsing_history_id)
        parsing = historical_parsing.instance
        pruning = get_pruning_by_history_id(pruning_parsing.pruning_history_id,
                                            pruning_by_history_id)
        parsing_by_pruning_uuid[pruning.uuid] = parsing

    scrapings = []
    scraping_by_history_id = {}
    prunings_by_scraping_uuid = {}
    for scheduling_scraping in scheduling.historical_scrapings.all():
        scraping_history_id = scheduling_scraping.scraping_history_id
        historical_scraping = Scraping.history.get(history_id=scraping_history_id)
        scraping = historical_scraping.instance
        scraping_by_history_id[scraping_history_id] = scraping
        scrapings.append(scraping)
        prunings_by_scraping_uuid[scraping.uuid] = []

    for scraping_pruning in scheduling.scraping_prunings.all():
        scraping_history_id = scraping_pruning.scraping_history_id
        scraping = scraping_by_history_id[scraping_history_id]
        pruning = get_pruning_by_history_id(scraping_pruning.pruning_history_id,
                                            pruning_by_history_id)
        prunings_by_scraping_uuid[scraping.uuid].append(pruning)

    images = []
    image_by_history_id = {}
    prunings_by_image_uuid = {}
    for scheduling_image in scheduling.historical_images.all():
        image_history_id = scheduling_image.image_history_id
        historical_image = Image.history.get(history_id=image_history_id)
        image = historical_image.instance
        image_by_history_id[image_history_id] = image
        images.append(image)
        prunings_by_image_uuid[image.uuid] = []

    for image_pruning in scheduling.image_prunings.all():
        image_history_id = image_pruning.image_history_id
        image = image_by_history_id[image_history_id]
        pruning = get_pruning_by_history_id(image_pruning.pruning_history_id,
                                            pruning_by_history_id)
        prunings_by_image_uuid[image.uuid].append(pruning)

    return SchedulingPrimarySources(
        scrapings=scrapings,
        images=images,
        prunings_by_scraping_uuid=prunings_by_scraping_uuid,
        prunings_by_image_uuid=prunings_by_image_uuid,
        parsing_by_pruning_uuid=parsing_by_pruning_uuid,
    )


##################
# RESOURCES HASH #
##################

def build_resources_hash(scheduling: Scheduling,
                         sourced_schedules_list: SourcedSchedulesList,
                         church_uuid_by_id: dict[int, str],
                         index_events: list[IndexEvent],
                         schedules_match_with_validated: bool | None) -> str:
    elements_to_hash = []

    # Churches
    elements_to_hash += sorted(map(
        lambda historical_church: historical_church.church_history_id,
        scheduling.historical_churches.all()))

    # Scrapings & Images
    elements_to_hash += sorted(map(
        lambda historical_scraping: historical_scraping.scraping_history_id,
        scheduling.historical_scrapings.all()))
    elements_to_hash += sorted(map(
        lambda historical_image: historical_image.image_history_id,
        scheduling.historical_images.all()))

    # Prunings & Parsings
    elements_to_hash += sorted(map(
        lambda scraping_pruning: (scraping_pruning.scraping_history_id,
                                  scraping_pruning.pruning_history_id),
        scheduling.scraping_prunings.all()
    ))
    elements_to_hash += sorted(map(
        lambda image_pruning: (image_pruning.image_history_id,
                               image_pruning.pruning_history_id),
        scheduling.image_prunings.all()
    ))
    elements_to_hash += sorted(map(
        lambda pruning_parsing: (pruning_parsing.pruning_history_id,
                                 pruning_parsing.parsing_history_id),
        scheduling.pruning_parsings.all()
    ))

    # OClocher
    elements_to_hash += sorted(map(
        lambda hol: hol.oclocher_location_history_id,
        scheduling.historical_oclocher_locations.all()))
    elements_to_hash += sorted(map(
        lambda hos: hos.oclocher_schedule_history_id,
        scheduling.historical_oclocher_schedules.all()))
    try:
        elements_to_hash += [scheduling.historical_oclocher_matching.oclocher_matching_history_id]
    except SchedulingHistoricalOClocherMatching.DoesNotExist:
        pass

    # sourced_schedules_list & church_uuid_by_id
    elements_to_hash += [sourced_schedules_list.hash_key()]
    elements_to_hash += sorted(church_uuid_by_id.items())
    # Index events
    elements_to_hash += sorted(map(
        lambda index_event: (
            index_event.church_id,
            index_event.day,
            index_event.start_time,
            index_event.indexed_end_time,
            index_event.displayed_end_time or datetime.time(0, 0),
            index_event.start_tz_datetime,
            index_event.indexed_end_tz_datetime,
            index_event.schedules_indices,
            index_event.has_been_moderated,
            index_event.church_color,
        ),
        index_events
    ))
    # schedules_match_with_validated
    elements_to_hash += [schedules_match_with_validated]

    return hash_string_to_hex(''.join(map(str, elements_to_hash)))


################
# GET WEBSITES #
################

def get_websites_of_prunings(prunings: list[Pruning]) -> list[Website]:
    history_ids = Subquery(
        Pruning.history.filter(
            uuid__in=[pruning.uuid for pruning in prunings]
        ).values('history_id')
    )

    return list(
        Website.objects.filter(
            schedulings__in=Scheduling.objects.filter(
                Q(scraping_prunings__pruning_history_id__in=history_ids)
                | Q(image_prunings__pruning_history_id__in=history_ids),
                status=Scheduling.Status.INDEXED,
            )
        ).distinct()
    )


def get_websites_of_parsing(parsing: Parsing) -> list[Website]:
    history_ids = Subquery(
        parsing.history.values('history_id')
    )

    return list(
        Website.objects.filter(
            schedulings__in=Scheduling.objects.filter(
                pruning_parsings__parsing_history_id__in=history_ids,
                status=Scheduling.Status.INDEXED,
            )
        ).distinct()
    )


################
# GET PRUNINGS #
################

def get_prunings_of_parsing(parsing: Parsing) -> list[Pruning]:
    history_ids = Subquery(
        parsing.history.values('history_id')
    )

    pruning_history_ids = Subquery(
        Scheduling.objects.filter(
            pruning_parsings__parsing_history_id__in=history_ids,
            status=Scheduling.Status.INDEXED,
        ).values('pruning_parsings__pruning_history_id')
    )

    return list(
        Pruning.history.filter(
            history_id__in=pruning_history_ids
        ).distinct()
    )


def get_parsing_moderation_of_pruning(pruning: Pruning) -> ParsingModeration | None:
    history_ids = Subquery(
        pruning.history.values('history_id')
    )

    parsing_history_ids = Subquery(
        Scheduling.objects.filter(
            pruning_parsings__pruning_history_id__in=history_ids,
            status=Scheduling.Status.INDEXED,
        ).values('pruning_parsings__parsing_history_id')
    )

    parsing_uuids = Parsing.history.filter(
        history_id__in=parsing_history_ids
    ).values_list('uuid', flat=True)

    return ParsingModeration.objects.filter(
        parsing__uuid__in=parsing_uuids
    ).first()
