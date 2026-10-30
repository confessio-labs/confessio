from datetime import datetime, date
from enum import Enum
from typing import Literal
from uuid import UUID

from django.http import Http404
from ninja import NinjaAPI, Schema, File, Form, Field
from ninja.errors import HttpError
from ninja.files import UploadedFile

from attaching.models import FileNote, TextNote
from attaching.public_service import attaching_get_file_note_public_url, \
    attaching_upload_file_note, attaching_find_error_in_document_to_upload, \
    attaching_recognize_and_extract_file_note, attaching_add_text_note, \
    attaching_extract_text_note, attaching_find_error_in_text_note_content
from core.models.base_models import BaseComment
from front.models import Approval, ApprovalComment, AutocompleteHit, Issue, IssueComment
from front.services.card.report_service import save_report, NewReportError, FeedbackType, \
    save_issue, save_approval, save_comment
from front.services.card.report_thread_service import get_report_threads, ReportThread
from front.services.card.scraping_url_service import get_scraping_parsing_urls
from front.services.card.sources_service import get_website_parsings_and_prunings, \
    WebsiteParsingsAndPrunings
from front.services.search.aggregation_service import get_search_results
from front.services.search.autocomplete_service import get_aggregated_response, AutocompleteResult
from front.services.search.search_service import TimeFilter, AggregationItem, BoundingBox, \
    get_dioceses_bounding_box, get_churches_by_uuid, get_churches_by_diocese, \
    get_churches_in_box, SearchResult, DEFAULT_LIMIT
from front.utils.web_utils import clean_email, find_error_in_email
from registry.models import Church, Website, Diocese, City
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
        file_note = parsings_and_prunings.file_note_by_parsing_uuid.get(parsing_uuid)
        return cls(
            uuid=parsing_uuid,
            scraping_url=scraping_url,
            image_url=attaching_get_file_note_public_url(file_note) if file_note else None,
        )


class FeedbackTypeEnum(str, Enum):
    GOOD = "good"
    ERROR = "error"
    COMMENT = "comment"


class ReportIn(Schema):
    website_uuid: UUID
    church_uuid: UUID | None = None
    feedback_type: FeedbackTypeEnum
    comment: str | None = None
    main_report_uuid: UUID | None = None
    email: str | None = None


class ReportOut(Schema):
    uuid: UUID
    created_at: datetime
    feedback_type: FeedbackTypeEnum
    comment: str | None
    sub_reports: list['ReportOut']

    @classmethod
    def from_report(cls, report: Issue | Approval | IssueComment | ApprovalComment,
                    sub_reports: list[IssueComment | ApprovalComment]) -> 'ReportOut':
        if isinstance(report, Approval):
            feedback_type = FeedbackTypeEnum.GOOD
        elif isinstance(report, Issue):
            feedback_type = FeedbackTypeEnum.ERROR
        else:
            feedback_type = FeedbackTypeEnum.COMMENT

        return cls(
            uuid=report.uuid,
            created_at=report.created_at,
            feedback_type=feedback_type,
            comment=report.content or None,
            sub_reports=[ReportOut.from_report(sub_report, []) for sub_report in sub_reports],
        )

    @classmethod
    def from_thread(cls, thread: ReportThread) -> 'ReportOut':
        return cls.from_report(thread.head, thread.comments)


class ImageOut(Schema):
    image_uuid: UUID
    public_url: str
    comment: str | None

    @classmethod
    def from_file_note(cls, file_note: FileNote) -> 'ImageOut':
        return cls(
            image_uuid=file_note.uuid,
            public_url=attaching_get_file_note_public_url(file_note),
            comment=file_note.caption,
        )


class CommentIn(Schema):
    content: str
    email: str | None = None


class CommentOut(Schema):
    uuid: UUID
    created_at: datetime
    content: str

    @classmethod
    def from_comment(cls, comment: BaseComment) -> 'CommentOut':
        return cls(
            uuid=comment.uuid,
            created_at=comment.created_at,
            content=comment.content,
        )


class IssueIn(Schema):
    website_uuid: UUID
    church_uuid: UUID | None = None
    content: str | None = None
    email: str | None = None


class IssueOut(Schema):
    uuid: UUID
    created_at: datetime
    church_uuid: UUID | None
    content: str
    solved_at: datetime | None
    comments: list[CommentOut]

    @classmethod
    def from_issue(cls, issue: Issue, comments: list[IssueComment]) -> 'IssueOut':
        return cls(
            uuid=issue.uuid,
            created_at=issue.created_at,
            church_uuid=issue.church_id,
            content=issue.content,
            solved_at=issue.solved_at,
            comments=[CommentOut.from_comment(comment) for comment in comments],
        )


class ApprovalIn(Schema):
    website_uuid: UUID
    church_uuid: UUID | None = None
    content: str | None = None
    email: str | None = None


class ApprovalOut(Schema):
    uuid: UUID
    created_at: datetime
    church_uuid: UUID | None
    content: str | None
    comments: list[CommentOut]

    @classmethod
    def from_approval(cls, approval: Approval, comments: list[ApprovalComment]
                      ) -> 'ApprovalOut':
        return cls(
            uuid=approval.uuid,
            created_at=approval.created_at,
            church_uuid=approval.church_id,
            content=approval.content or None,
            comments=[CommentOut.from_comment(comment) for comment in comments],
        )


class TextNoteIn(Schema):
    website_uuid: UUID
    content: str
    email: str | None = None


class TextNoteOut(Schema):
    uuid: UUID
    created_at: datetime
    content: str
    expire_at: datetime
    comments: list[CommentOut]

    @classmethod
    def from_text_note(cls, text_note: TextNote, comments: list[BaseComment]
                       ) -> 'TextNoteOut':
        return cls(
            uuid=text_note.uuid,
            created_at=text_note.created_at,
            content=text_note.content,
            expire_at=text_note.expire_at,
            comments=[CommentOut.from_comment(comment) for comment in comments],
        )


class FileNoteOut(Schema):
    uuid: UUID
    created_at: datetime
    public_url: str
    caption: str | None
    expire_at: datetime
    comments: list[CommentOut]

    @classmethod
    def from_file_note(cls, file_note: FileNote, comments: list[BaseComment]
                       ) -> 'FileNoteOut':
        return cls(
            uuid=file_note.uuid,
            created_at=file_note.created_at,
            public_url=attaching_get_file_note_public_url(file_note),
            caption=file_note.caption,
            expire_at=file_note.expire_at,
            comments=[CommentOut.from_comment(comment) for comment in comments],
        )


class WebsiteOut(Schema):
    uuid: UUID
    name: str
    home_url: str
    reports: list[ReportOut] = Field(deprecated='Use issues and approvals instead')
    images: list[ImageOut] = Field(deprecated='Use file_notes instead')
    issues: list[IssueOut]
    approvals: list[ApprovalOut]
    text_notes: list[TextNoteOut]
    file_notes: list[FileNoteOut]

    @classmethod
    def from_website_and_threads(cls,
                                 website: Website,
                                 threads: list[ReportThread],
                                 ):
        # Legacy images are listed oldest first, threads newest first
        file_notes = FileNote.objects.filter(website=website).order_by('created_at')

        return cls(
            uuid=website.uuid,
            name=website.name,
            home_url=website.home_url,
            reports=[ReportOut.from_thread(thread) for thread in threads
                     if thread.is_issue or thread.is_approval],
            images=[ImageOut.from_file_note(file_note) for file_note in file_notes],
            issues=[IssueOut.from_issue(thread.head, thread.comments)
                    for thread in threads if thread.is_issue],
            approvals=[ApprovalOut.from_approval(thread.head, thread.comments)
                       for thread in threads if thread.is_approval],
            text_notes=[TextNoteOut.from_text_note(thread.head, thread.comments)
                        for thread in threads if thread.is_text_note],
            file_notes=[FileNoteOut.from_file_note(thread.head, thread.comments)
                        for thread in threads if thread.is_file_note],
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


class CityOut(Schema):
    insee_code: str
    name: str
    slug: str
    zipcode: str
    population: int
    latitude: float
    longitude: float

    @classmethod
    def from_city(cls, city: City) -> 'CityOut':
        return cls(
            insee_code=city.insee_code,
            name=city.name,
            slug=city.slug,
            zipcode=city.zipcode,
            population=city.population,
            latitude=city.location.y,
            longitude=city.location.x,
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
    search_result = get_churches_in_box(min_lat, min_lng, max_lat, max_lng, time_filter)
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

    website_out = WebsiteOut.from_website_and_threads(website, get_report_threads(website))

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


@api.get("/cities", response=list[CityOut])
def api_front_get_cities(request, limit: int = 100, offset: int = 0) -> list[CityOut]:
    limit = max(0, min(1000, limit))
    offset = max(0, offset)
    cities = City.objects.filter(slug__isnull=False) \
        .order_by('-population', 'insee_code')[offset:offset + limit]
    return [CityOut.from_city(city) for city in cities]


@api.get("/city/{city_slug}", response={200: CityOut, 404: ErrorSchema})
def api_front_get_city(request, city_slug: str) -> CityOut:
    try:
        city = City.objects.get(slug=city_slug)
    except City.DoesNotExist:
        raise Http404(f'City with slug {city_slug} not found')
    return CityOut.from_city(city)


def get_website_or_404(website_uuid: UUID) -> Website:
    try:
        return Website.objects.get(uuid=website_uuid)
    except Website.DoesNotExist:
        raise Http404(f'Website {website_uuid} does not exist')


def get_church_or_404(church_uuid: UUID | None) -> Church | None:
    if church_uuid is None:
        return None

    try:
        return Church.objects.get(uuid=church_uuid)
    except Church.DoesNotExist:
        raise Http404(f'Church {church_uuid} does not exist')


def clean_and_check_email(email: str | None) -> str | None:
    email = clean_email(email)
    email_error = find_error_in_email(email)
    if email_error:
        raise HttpError(400, email_error)

    return email


@api.post("/reports", response={200: ReportOut, 400: ErrorSchema, 404: ErrorSchema},
          deprecated=True)
def api_front_post_reports(request, report_in: ReportIn) -> ReportOut:
    website = get_website_or_404(report_in.website_uuid)
    church = get_church_or_404(report_in.church_uuid)
    email = clean_and_check_email(report_in.email)

    try:
        report = save_report(
            request, website, church,
            FeedbackType(report_in.feedback_type),
            report_in.comment, report_in.main_report_uuid, email,
        )
    except NewReportError as e:
        if e.status == 404:
            raise Http404(e.message)
        raise HttpError(e.status, e.message)

    return ReportOut.from_report(report, [])


@api.post("/images", response={200: ImageOut, 400: ErrorSchema, 404: ErrorSchema},
          deprecated=True)
def api_front_post_images(request,
                          website_uuid: UUID = Form(...),
                          document: UploadedFile = File(...),
                          comment: str | None = Form(None),
                          email: str | None = Form(None)) -> ImageOut:
    file_note = upload_file_note(request, website_uuid, document, comment, email)
    return ImageOut.from_file_note(file_note)


@api.post("/issues", response={200: IssueOut, 400: ErrorSchema, 404: ErrorSchema})
def api_front_post_issue(request, issue_in: IssueIn) -> IssueOut:
    website = get_website_or_404(issue_in.website_uuid)
    church = get_church_or_404(issue_in.church_uuid)
    email = clean_and_check_email(issue_in.email)

    issue = save_issue(request, website, church, issue_in.content, email)
    return IssueOut.from_issue(issue, [])


@api.post("/approvals", response={200: ApprovalOut, 400: ErrorSchema, 404: ErrorSchema})
def api_front_post_approval(request, approval_in: ApprovalIn) -> ApprovalOut:
    website = get_website_or_404(approval_in.website_uuid)
    church = get_church_or_404(approval_in.church_uuid)
    email = clean_and_check_email(approval_in.email)

    approval = save_approval(request, website, church, approval_in.content, email)
    return ApprovalOut.from_approval(approval, [])


@api.post("/text_notes", response={200: TextNoteOut, 400: ErrorSchema, 404: ErrorSchema})
def api_front_post_text_note(request, text_note_in: TextNoteIn) -> TextNoteOut:
    website = get_website_or_404(text_note_in.website_uuid)
    content_error = attaching_find_error_in_text_note_content(text_note_in.content)
    if content_error:
        raise HttpError(400, content_error)
    email = clean_and_check_email(text_note_in.email)

    text_note, error_message = attaching_add_text_note(text_note_in.content, website, request,
                                                       email)
    if text_note is None:
        raise HttpError(400, error_message or 'Text note creation failed')

    attaching_extract_text_note(text_note)

    return TextNoteOut.from_text_note(text_note, [])


@api.post("/file_notes", response={200: FileNoteOut, 400: ErrorSchema, 404: ErrorSchema})
def api_front_post_file_note(request,
                             website_uuid: UUID = Form(...),
                             document: UploadedFile = File(...),
                             caption: str | None = Form(None),
                             email: str | None = Form(None)) -> FileNoteOut:
    file_note = upload_file_note(request, website_uuid, document, caption, email)
    return FileNoteOut.from_file_note(file_note, [])


def upload_file_note(request, website_uuid: UUID, document: UploadedFile,
                     caption: str | None, email: str | None) -> FileNote:
    website = get_website_or_404(website_uuid)

    email = clean_email(email)
    validation_error = attaching_find_error_in_document_to_upload(document) \
        or find_error_in_email(email)
    if validation_error:
        raise HttpError(400, validation_error)

    file_note, error_message = attaching_upload_file_note(document, website, request,
                                                          caption=caption, email=email)
    if file_note is None:
        raise HttpError(400, error_message or 'Upload failed')

    attaching_recognize_and_extract_file_note(file_note)

    return file_note


def post_comment(request, head: Issue | Approval | FileNote | TextNote,
                 comment_in: CommentIn) -> CommentOut:
    email = clean_and_check_email(comment_in.email)
    comment = save_comment(request, head.website, head.church, head, comment_in.content, email)
    return CommentOut.from_comment(comment)


def get_head_or_404(model: type[Issue | Approval | FileNote | TextNote], head_uuid: UUID
                    ) -> Issue | Approval | FileNote | TextNote:
    try:
        return model.objects.select_related('website', 'church').get(uuid=head_uuid)
    except model.DoesNotExist:
        raise Http404(f'{model.__name__} {head_uuid} does not exist')


@api.post("/issues/{issue_uuid}/comments",
          response={200: CommentOut, 400: ErrorSchema, 404: ErrorSchema})
def api_front_post_issue_comment(request, issue_uuid: UUID, comment_in: CommentIn
                                 ) -> CommentOut:
    return post_comment(request, get_head_or_404(Issue, issue_uuid), comment_in)


@api.post("/approvals/{approval_uuid}/comments",
          response={200: CommentOut, 400: ErrorSchema, 404: ErrorSchema})
def api_front_post_approval_comment(request, approval_uuid: UUID, comment_in: CommentIn
                                    ) -> CommentOut:
    return post_comment(request, get_head_or_404(Approval, approval_uuid), comment_in)


@api.post("/text_notes/{text_note_uuid}/comments",
          response={200: CommentOut, 400: ErrorSchema, 404: ErrorSchema})
def api_front_post_text_note_comment(request, text_note_uuid: UUID, comment_in: CommentIn
                                     ) -> CommentOut:
    return post_comment(request, get_head_or_404(TextNote, text_note_uuid), comment_in)


@api.post("/file_notes/{file_note_uuid}/comments",
          response={200: CommentOut, 400: ErrorSchema, 404: ErrorSchema})
def api_front_post_file_note_comment(request, file_note_uuid: UUID, comment_in: CommentIn
                                     ) -> CommentOut:
    return post_comment(request, get_head_or_404(FileNote, file_note_uuid), comment_in)
