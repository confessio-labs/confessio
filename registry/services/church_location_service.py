from typing import Optional

from django.contrib.gis.geos import Point
from registry.models import ChurchModeration, Church, ExternalSource, Diocese
from registry.models.base_moderation_models import ModerationStatus
from registry.utils.geo_utils import get_distances_to_barycenter, check_coordinates_validity
from registry.utils.google_maps_api_utils import google_maps_geocode
from registry.utils.wikidata_utils import get_church_by_messesinfo_id


def get_church_external_source(church: Church) -> ExternalSource:
    if church.annuairecatholique_id:
        return ExternalSource.ANNUAIRECATHOLIQUE
    elif church.trouverunemesse_id:
        return ExternalSource.TROUVERUNEMESSE  # legacy, no longer written
    elif church.messesinfo_id:
        return ExternalSource.MESSESINFO
    else:
        return ExternalSource.MANUAL


def compute_church_coordinates(
        church: Church, source: ExternalSource | None = None, no_save: bool = False
) -> list[tuple[ChurchModeration.Category, bool]] | None:
    if source is None:
        source = get_church_external_source(church)

    wikidata_results = get_church_by_messesinfo_id(church.messesinfo_id)
    if wikidata_results and len(wikidata_results) == 1 and wikidata_results[0].coordinates_latlon:
        result = wikidata_results[0]
        church.wikidata_id = result.q_number
    else:
        result = google_maps_geocode(church.name, church.city, church.zipcode)

    categories = []
    if not result or not result.coordinates_latlon:
        categories.append((ChurchModeration.Category.LOCATION_NULL, False))
    else:
        if church.wikidata_id is None:
            categories.append((ChurchModeration.Category.LOCATION_FROM_API, False))
        latitude, longitude = result.coordinates_latlon
        church.location = Point(longitude, latitude)
        if not church.address:
            church.address = result.address
        if not church.zipcode:
            church.zipcode = result.zipcode
        if not church.city:
            church.city = result.city

    church_with_same_location = get_church_with_same_location(church)
    if church_with_same_location:
        # We can not save church since another church already has the same location
        add_church_location_conflict(church_with_same_location, church, source)
        return None

    if source != ExternalSource.MANUAL:
        categories.append((ChurchModeration.Category.LOCATION_DIFFERS, True))

    if no_save:
        return categories

    church.save()
    for category, validated in categories:
        add_church_moderation_if_not_exists(church, category, source, validated=validated)

    return None


def get_church_moderation(church: Church, category: ChurchModeration.Category,
                          source: ExternalSource | None = None):
    if source is None:
        source = get_church_external_source(church)
    try:
        return ChurchModeration.objects.get(
            church=church,
            category=category,
            source=source
        )
    except ChurchModeration.DoesNotExist:
        return None


def add_church_moderation_if_not_exists(church: Church, category: ChurchModeration.Category,
                                        source: ExternalSource | None = None,
                                        validated: bool = False):
    if source is None:
        source = get_church_external_source(church)
    church_moderation = get_church_moderation(church, category, source)
    if church_moderation:
        if validated and church_moderation.status != ModerationStatus.VALIDATED:
            church_moderation.status = ModerationStatus.VALIDATED
            church_moderation.save()
    else:
        church_moderation = ChurchModeration(
            church=church,
            category=category,
            source=source,
            location=church.location,
            address=church.address,
            zipcode=church.zipcode,
            city=church.city,
            diocese=church.parish.diocese,
            status=(ModerationStatus.VALIDATED
                    if validated
                    else ModerationStatus.TO_VALIDATE),
        )
        church_moderation.save()


def add_church_location_conflict(existing_church: Church, church: Church,
                                 source: ExternalSource):
    church_moderation = ChurchModeration(
        church=existing_church,
        category=ChurchModeration.Category.LOCATION_CONFLICT,
        source=source,
        name=church.name,
        address=church.address,
        zipcode=church.zipcode,
        city=church.city,
        messesinfo_id=church.messesinfo_id,
        diocese=existing_church.parish.diocese,
        status=ModerationStatus.TO_VALIDATE,
    )

    try:
        existing_moderation = ChurchModeration.objects.get(
            church=church_moderation.church,
            category=church_moderation.category,
            source=church_moderation.source
        )
        if existing_moderation.name != church_moderation.name:
            existing_moderation.delete()
            church_moderation.save()
    except ChurchModeration.DoesNotExist:
        church_moderation.save()


def get_church_with_same_location(church: Church) -> Optional[Church]:
    try:
        return Church.objects.filter(location=church.location).exclude(pk=church.pk).first()
    except Church.DoesNotExist:
        return None


############
# OUTLIERS #
############

def find_church_geo_outliers() -> int:
    outliers_count = 0
    for diocese in Diocese.objects.all():
        print(f'Scanning diocese {diocese.name}')
        diocese_churches = []
        outliers_churches = []
        for parish in diocese.parishes.all():
            parish_churches = []
            for church in parish.churches.all():
                diocese_churches.append(church)
                parish_churches.append(church)

            outliers_churches += check_distances(parish_churches, 45_000)

        for church in check_distances(diocese_churches, 110_000):
            if church not in outliers_churches:
                outliers_churches.append(church)

        for church in diocese_churches:
            if church in outliers_churches:
                church_moderation = get_church_moderation(
                    church, ChurchModeration.Category.LOCATION_OUTLIER)
                if not church_moderation:
                    compute_church_coordinates(church, no_save=True)
                add_church_moderation_if_not_exists(church,
                                                    ChurchModeration.Category.LOCATION_OUTLIER)
            else:
                ChurchModeration.objects.filter(
                    church=church,
                    category=ChurchModeration.Category.LOCATION_OUTLIER,
                ).exclude(status=ModerationStatus.VALIDATED).delete()

        outliers_count += len(outliers_churches)

    return outliers_count


def check_distances(churches: list[Church], max_distance: int) -> list[Church]:
    valid_churches = []
    for church in churches:
        if not check_coordinates_validity(church.location):
            compute_church_coordinates(church)
            continue
        valid_churches.append(church)

    distance_by_point = get_distances_to_barycenter([c.location for c in valid_churches])

    outliers_churches = []
    for church in valid_churches:
        if distance_by_point[church.location] > max_distance:
            print(f'Church {church.name} ({church.city}, {church.uuid}) is an outlier, '
                  f'distance: {int(distance_by_point[church.location])} m (max: {max_distance} m)')
            outliers_churches.append(church)

    return outliers_churches
