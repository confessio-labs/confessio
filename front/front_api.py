from datetime import datetime, date
from enum import Enum
from typing import Literal
from uuid import UUID

from django.http import Http404
from ninja import NinjaAPI, Schema, File, Form
from ninja.errors import HttpError
from ninja.files import UploadedFile

from attaching.models import Image
from attaching.public_service import attaching_get_image_public_url, \
    attaching_upload_image, attaching_find_error_in_document_to_upload, \
    attaching_recognize_and_extract_image
from front.models import Report, AutocompleteHit
from front.services.card.report_service import save_report
from front.services.card.scraping_url_service import get_scraping_parsing_urls
from front.services.card.sources_service import get_website_parsings_and_prunings, \
    WebsiteParsingsAndPrunings
from front.services.search.aggregation_service import get_search_results
from front.services.search.autocomplete_service import get_aggregated_response, AutocompleteResult
from front.services.search.search_service import TimeFilter, AggregationItem, BoundingBox, \
    get_dioceses_bounding_box, get_churches_by_uuid, get_churches_by_diocese, \
    get_popular_churches, SearchResult, DEFAULT_LIMIT
from registry.models import Church, Website, Diocese
from scheduling.models import IndexEvent
from scheduling.public_model import SourcedScheduleItem, BaseSource, ParsingSource, OClocherSource
from scheduling.public_service import scheduling_get_indexed_scheduling, \
    scheduling_retrieve_scheduling_elements, scheduling_get_scheduling_primary_sources
from scheduling.public_model import PeriodEnum

api = NinjaAPI(urls_namespace='front_api')


##########
# MODELS #
##########


class EventOut(Schema):
    start: datetime
    end: datetime | None
    schedules_indices: list[int]
    source_has_been_moderated: bool
    periods: list[PeriodEnum]

    @classmethod
    def from_index_event(cls, index_event: IndexEvent) -> 'EventOut':
        start = datetime.combine(index_event.day, index_event.start_time)
        end = datetime.combine(index_event.day, index_event.displayed_end_time) \
            if index_event.displayed_end_time else None

        return cls(
            start=start,
            end=end,
            schedules_indices=index_event.schedules_indices,
            source_has_been_moderated=index_event.has_been_moderated,
            periods=index_event.periods,
        )


class ChurchOut(Schema):
    uuid: UUID
    name: str
    latitude: float
    longitude: float
    address: str | None
    zipcode: str | None
    city: str | None
    events: list[EventOut]

    @classmethod
    def from_church_and_events(cls, church: Church, index_events: list[IndexEvent]) -> 'ChurchOut':
        return cls(
            uuid=church.uuid,
            name=church.name,
            latitude=church.location.y,
            longitude=church.location.x,
            address=church.address,
            zipcode=church.zipcode,
            city=church.city,
            events=[EventOut.from_index_event(event) for event in sorted(index_events)],
        )


class SourceTypeEnum(str, Enum):
    PARSING = 'parsing'
    OCLOCHER = 'oclocher'


class SourceOut(Schema):
    source_type: SourceTypeEnum
    parsing_uuid: UUID | None

    @classmethod
    def from_source(cls, source: BaseSource) -> 'SourceOut':
        if isinstance(source, ParsingSource):
            return cls(
                source_type=SourceTypeEnum.PARSING,
                parsing_uuid=source.parsing_uuid,
            )
        if isinstance(source, OClocherSource):
            return cls(
                source_type=SourceTypeEnum.OCLOCHER,
                parsing_uuid=None,
            )

        raise ValueError(f'Unknown source type: {type(source)}')


class ScheduleOut(Schema):
    explanation: str
    sources: list[SourceOut]

    @classmethod
    def from_sourced_schedule_item(cls,
                                   sourced_schedule_item: SourcedScheduleItem) -> 'ScheduleOut':
        return cls(
            explanation=sourced_schedule_item.explanation,
            sources=[SourceOut.from_source(source) for source in sourced_schedule_item.sources],
        )


class ParsingOut(Schema):
    uuid: UUID
    scraping_url: str | None
    image_url: str | None

    @classmethod
    def from_parsing_and_related(cls, parsing_uuid: UUID,
                                 parsings_and_prunings: WebsiteParsingsAndPrunings,
                                 scraping_parsing_urls: dict[UUID, dict[UUID, str]],
                                 ) -> 'ParsingOut':
        scraping = parsings_and_prunings.scraping_by_parsing_uuid.get(parsing_uuid)
        scraping_url = scraping_parsing_urls[scraping.uuid][parsing_uuid] \
            if scraping else None
        image = parsings_and_prunings.image_by_parsing_uuid.get(parsing_uuid)
        return cls(
            uuid=parsing_uuid,
            scraping_url=scraping_url,
            image_url=attaching_get_image_public_url(image) if image else None,
        )


class FeedbackTypeEnum(str, Enum):
    GOOD = "good"
    ERROR = "error"
    COMMENT = "comment"


class ErrorTypeEnum(str, Enum):
    OUTDATED = "outdated"
    CHURCHES = "churches"
    PARAGRAPHS = "paragraphs"
    SCHEDULES = "schedules"


class ReportIn(Schema):
    website_uuid: UUID
    church_uuid: UUID | None = None
    feedback_type: FeedbackTypeEnum
    error_type: ErrorTypeEnum | None = None
    comment: str | None = None


class ReportOut(Schema):
    created_at: datetime
    feedback_type: FeedbackTypeEnum
    comment: str | None
    sub_reports: list['ReportOut']

    @classmethod
    def from_report(cls, report: Report, sub_reports: list[Report]) -> 'ReportOut':
        return cls(
            created_at=report.created_at,
            feedback_type=FeedbackTypeEnum(report.feedback_type),
            comment=report.comment,
            sub_reports=[ReportOut.from_report(report, []) for report in sub_reports],
        )


class ImageOut(Schema):
    image_uuid: UUID
    public_url: str

    @classmethod
    def from_image(cls, image: Image) -> 'ImageOut':
        return cls(
            image_uuid=image.uuid,
            public_url=attaching_get_image_public_url(image),
        )


class WebsiteOut(Schema):
    uuid: UUID
    name: str
    home_url: str
    reports: list[ReportOut]
    images: list[ImageOut]

    @classmethod
    def from_website(cls,
                     website: Website,
                     reports: list[ReportOut],
                     images: list[ImageOut],
                     ):
        return cls(
            uuid=website.uuid,
            name=website.name,
            home_url=website.home_url,
            reports=reports,
            images=images,
        )


class ChurchDetails(ChurchOut):
    website: WebsiteOut
    schedules: list[ScheduleOut]
    parsings: list[ParsingOut]

    @classmethod
    def from_church_and_schedules(cls, church: Church, index_events: list[IndexEvent],
                                  website: WebsiteOut,
                                  schedules: list[ScheduleOut],
                                  parsings: list[ParsingOut],
                                  ) -> 'ChurchDetails':
        base = ChurchOut.from_church_and_events(church, index_events)

        return cls(
            **base.dict(),
            website=website,
            schedules=schedules,
            parsings=parsings,
        )


class AggregationOut(Schema):
    type: Literal['diocese', 'parish', 'municipality']
    name: str
    church_count: int
    church_with_event_count: int
    centroid_latitude: float
    centroid_longitude: float
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float

    @classmethod
    def from_aggregation(cls, aggregation: AggregationItem):
        return cls(
            type=aggregation.type,
            name=aggregation.name,
            church_count=aggregation.church_count,
            church_with_event_count=aggregation.church_with_event_count,
            centroid_latitude=aggregation.centroid_latitude,
            centroid_longitude=aggregation.centroid_longitude,
            min_latitude=aggregation.min_latitude,
            max_latitude=aggregation.max_latitude,
            min_longitude=aggregation.min_longitude,
            max_longitude=aggregation.max_longitude,
        )


class SearchResultOut(Schema):
    churches: list[ChurchOut]
    aggregations: list[AggregationOut]

    @classmethod
    def from_result(cls,
                    search_result: SearchResult,
                    aggregation_items: list[AggregationItem],):
        index_events_by_church = {}
        for index_event in search_result.index_events:
            index_events_by_church.setdefault(index_event.church.uuid, []).append(index_event)

        churches = [ChurchOut.from_church_and_events(church,
                                                     index_events_by_church.get(church.uuid, []))
                    for church in search_result.churches]
        aggregations = [AggregationOut.from_aggregation(aggregation)
                        for aggregation in aggregation_items]

        return cls(
            churches=churches,
            aggregations=aggregations,
        )


class AutocompleteItem(Schema):
    type: str
    name: str
    context: str | None
    url: str
    latitude: float | None = None
    longitude: float | None = None
    uuid: UUID | None = None
    church_uuid: UUID | None = None

    @classmethod
    def from_autocomplete_result(cls, result: AutocompleteResult):
        return cls(
            type=result.type,
            name=result.name,
            context=result.context,
            url=result.url,
            latitude=result.latitude,
            longitude=result.longitude,
            uuid=result.uuid,
            church_uuid=result.church_uuid,
        )


class AutocompleteHitIn(Schema):
    query: str
    latitude: float | None
    longitude: float | None
    rank: int
    item: AutocompleteItem


class DioceseOut(Schema):
    uuid: UUID
    name: str
    slug: str
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float

    @classmethod
    def from_diocese_and_box(cls, diocese: Diocese, bounding_box: BoundingBox) -> 'DioceseOut':
        return cls(
            uuid=diocese.uuid,
            name=diocese.name,
            slug=diocese.slug,
            min_latitude=bounding_box.min_latitude,
            max_latitude=bounding_box.max_latitude,
            min_longitude=bounding_box.min_longitude,
            max_longitude=bounding_box.max_longitude,
        )


class ErrorSchema(Schema):
    detail: str


#############
# ENDPOINTS #
#############

@api.get("/search", response=SearchResultOut)
def api_front_search(request,
                     latitude: float | None = None,
                     longitude: float | None = None,
                     min_lat: float | None = None,
                     min_lng: float | None = None,
                     max_lat: float | None = None,
                     max_lng: float | None = None,
                     date_filter: date | None = None,
                     hour_min: int = 0, hour_max: int = 24 * 60 - 1,
                     limit: int = DEFAULT_LIMIT,
                     ) -> SearchResultOut:
    time_filter = TimeFilter(
        day_filter=date_filter,
        hour_min=hour_min,
        hour_max=hour_max,
        limit=limit,
    )
    search_result, aggregations = \
        get_search_results(latitude, longitude, min_lat, min_lng, max_lat, max_lng, time_filter)

    return SearchResultOut.from_result(search_result, aggregations)


@api.get("/search/home", response=SearchResultOut)
def api_front_search_home(request,
                          min_lat: float,
                          min_lng: float,
                          max_lat: float,
                          max_lng: float,
                          date_filter: date | None = None,
                          hour_min: int = 0, hour_max: int = 24 * 60 - 1,
                          limit: int = DEFAULT_LIMIT,
                          ) -> SearchResultOut:
    time_filter = TimeFilter(
        day_filter=date_filter,
        hour_min=hour_min,
        hour_max=hour_max,
        limit=limit,
    )
    search_result = get_popular_churches(min_lat, min_lng, max_lat, max_lng, time_filter)
    aggregations = []

    return SearchResultOut.from_result(search_result, aggregations)


@api.get("/search/diocese/{diocese_uuid}", response={200: SearchResultOut, 404: ErrorSchema})
def api_front_search_diocese(request,
                             diocese_uuid: UUID,
                             date_filter: date | None = None,
                             hour_min: int = 0, hour_max: int = 24 * 60 - 1,
                             limit: int = DEFAULT_LIMIT,
                             ) -> SearchResultOut:
    time_filter = TimeFilter(
        day_filter=date_filter,
        hour_min=hour_min,
        hour_max=hour_max,
        limit=limit,
    )
    try:
        diocese = Diocese.objects.get(uuid=diocese_uuid)
    except Diocese.DoesNotExist:
        raise Http404(f'Diocese with uuid {diocese_uuid} not found')

    search_result = get_churches_by_diocese(diocese, time_filter)
    aggregations = []

    return SearchResultOut.from_result(search_result, aggregations)


@api.get("/church/{church_uuid}", response={200: ChurchDetails, 404: ErrorSchema})
def api_front_church_details(request, church_uuid: UUID,
                             date_filter: date | None = None,
                             hour_min: int = 0,
                             hour_max: int = 24 * 60 - 1,
                             limit: int = DEFAULT_LIMIT,
                             ) -> ChurchDetails:
    time_filter = TimeFilter(
        day_filter=date_filter,
        hour_min=hour_min,
        hour_max=hour_max,
        limit=limit,
    )

    search_result = get_churches_by_uuid(church_uuid, time_filter)
    churches = list(search_result.churches)

    if not churches:
        raise Http404(f'Church with uuid {church_uuid} not found')

    church = churches[0]

    website = church.parish.website

    # Reports
    website_reports = list(Report.objects.filter(website=website).order_by('created_at').all())
    main_reports = []
    sub_reports_by_main_report = {}
    for report in website_reports:
        if report.main_report:
            sub_reports_by_main_report[report.main_report.uuid].append(report)
        else:
            main_reports.append(report)
            sub_reports_by_main_report[report.uuid] = []
    reports = [ReportOut.from_report(main_report, sub_reports_by_main_report[main_report.uuid])
               for main_report in reversed(main_reports)]

    # Images
    website_images = list(Image.objects.filter(website=website).order_by('created_at').all())
    images = [ImageOut.from_image(image) for image in website_images]

    website_out = WebsiteOut.from_website(website, reports, images)

    # Schedules
    scheduling = scheduling_get_indexed_scheduling(website)

    scheduling_elements = scheduling_retrieve_scheduling_elements(scheduling)
    church_id_list = [church_id for (church_id, church)
                      in scheduling_elements.church_by_id.items() if church.uuid == church_uuid]
    if not church_id_list:
        # Church is not indexed yet, we return it with no schedule
        return ChurchDetails.from_church_and_schedules(church,
                                                       search_result.index_events,
                                                       website_out, [], [])

    assert len(church_id_list) == 1, f'Multiple church ids found for church uuid {church_uuid}'
    church_id = church_id_list[0]

    sourced_schedules = [
        ssi for ssc in scheduling_elements.sourced_schedules_list.sourced_schedules_of_churches
        for ssi in ssc.sourced_schedules if ssc.church_id == church_id]
    schedules = [ScheduleOut.from_sourced_schedule_item(ssi) for ssi in sourced_schedules]

    # Parsings
    primary_sources = scheduling_get_scheduling_primary_sources(scheduling)
    parsings_and_prunings = get_website_parsings_and_prunings(primary_sources)
    scraping_parsing_urls = get_scraping_parsing_urls(primary_sources)
    parsing_uuids = {source.parsing_uuid for ssi in sourced_schedules
                     for source in ssi.sources if isinstance(source, ParsingSource)}
    parsings = [ParsingOut.from_parsing_and_related(parsing_uuid,
                                                    parsings_and_prunings,
                                                    scraping_parsing_urls)
                for parsing_uuid in parsing_uuids]

    return ChurchDetails.from_church_and_schedules(church, search_result.index_events, website_out,
                                                   schedules, parsings)


@api.get("/autocomplete", response=list[AutocompleteItem])
async def api_front_autocomplete(request, query: str,
                                 latitude: float | None = None,
                                 longitude: float | None = None) -> list[AutocompleteItem]:
    results = await get_aggregated_response(query, latitude, longitude)
    return list(map(lambda r: AutocompleteItem.from_autocomplete_result(r), results))


@api.post("/autocomplete/hits", response=AutocompleteHitIn)
def api_front_post_autocomplete_hit(request,
                                    autocomplete_hit_in: AutocompleteHitIn
                                    ) -> AutocompleteHitIn:
    autocomplete_hit = AutocompleteHit(
        query=autocomplete_hit_in.query,
        rank=autocomplete_hit_in.rank,
        latitude=autocomplete_hit_in.latitude,
        longitude=autocomplete_hit_in.longitude,
        item_type=autocomplete_hit_in.item.type,
        item_name=autocomplete_hit_in.item.name,
        item_context=autocomplete_hit_in.item.context,
        item_latitude=autocomplete_hit_in.item.latitude,
        item_longitude=autocomplete_hit_in.item.longitude,
        item_uuid=autocomplete_hit_in.item.uuid,
    )
    autocomplete_hit.save()
    return autocomplete_hit_in


@api.get("/dioceses", response={200: list[DioceseOut], 404: ErrorSchema})
def api_front_get_dioceses(request) -> list[DioceseOut]:
    dioceses_and_box = get_dioceses_bounding_box()
    return [DioceseOut.from_diocese_and_box(diocese, bounding_box)
            for diocese, bounding_box in dioceses_and_box]


@api.post("/reports", response={200: ReportOut, 404: ErrorSchema})
def api_front_post_reports(request, report_in: ReportIn) -> ReportOut:
    try:
        website = Website.objects.get(uuid=report_in.website_uuid)
    except Website.DoesNotExist:
        raise Http404(f'Website {report_in.website_uuid} does not exist')

    church = None
    if report_in.church_uuid:
        try:
            church = Church.objects.get(uuid=report_in.church_uuid)
        except Church.DoesNotExist:
            raise Http404(f'Church {report_in.church_uuid} does not exist')

    report = Report(
        website=website,
        church=church,
        feedback_type=Report.FeedbackType(report_in.feedback_type),
        error_type=Report.ErrorType(report_in.error_type) if report_in.error_type else None,
        comment=report_in.comment,
    )
    save_report(request, report)
    report.refresh_from_db()

    return ReportOut.from_report(report, [])


@api.post("/images", response={200: ImageOut, 400: ErrorSchema, 404: ErrorSchema})
def api_front_post_images(request,
                          website_uuid: UUID = Form(...),
                          document: UploadedFile = File(...),
                          comment: str | None = Form(None)) -> ImageOut:
    try:
        website = Website.objects.get(uuid=website_uuid)
    except Website.DoesNotExist:
        raise Http404(f'Website {website_uuid} does not exist')

    validation_error = attaching_find_error_in_document_to_upload(document)
    if validation_error:
        raise HttpError(400, validation_error)

    image, error_message = attaching_upload_image(document, website, request,
                                                  comment=comment)
    if image is None:
        raise HttpError(400, error_message or 'Upload failed')

    attaching_recognize_and_extract_image(image)

    return ImageOut.from_image(image)
