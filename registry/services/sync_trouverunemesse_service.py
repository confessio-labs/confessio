from django.contrib.gis.geos import Point

from registry.models import Church, ChurchModeration, ExternalSource
from registry.models.base_moderation_models import ModerationStatus
from registry.services.church_human_service import church_location_has_been_checked_by_human
from registry.utils.geo_utils import get_geo_distance
from registry.utils.trouverunemesse_utils import fetch_trouverunemesse_by_messesinfo_id, \
    TrouverUneMesseChurch, fetch_trouverunemesse_by_slug


def add_church_moderation_if_not_exists(church_moderation: ChurchModeration):
    try:
        ChurchModeration.objects.get(
            church=church_moderation.church,
            category=church_moderation.category,
            source=church_moderation.source
        )
    except ChurchModeration.DoesNotExist:
        church_moderation.save()


def sync_trouverunemesse_for_church(church: Church
                                    ) -> tuple[bool | None, bool | None]:
    if church.trouverunemesse_slug:
        print(f"Church {church.name} already has a trouverunemesse_slug, skipping sync.")
        return None

    if not church.messesinfo_id:
        print(f"Church {church.name} does not have a messesinfo_id, skipping sync.")
        return None

    trouverunemesse_church = fetch_trouverunemesse_by_messesinfo_id(church.messesinfo_id)
    if not trouverunemesse_church:
        print(f"Could not find trouverunemesse church for messesinfo_id {church.messesinfo_id}")
        return None

    church.trouverunemesse_id = trouverunemesse_church.id
    church.trouverunemesse_slug = trouverunemesse_church.slug
    church.save()

    return sync_trouverunemesse_location_and_name(church, trouverunemesse_church)


def sync_trouverunemesse_location_and_name(church: Church,
                                           trouverunemesse_church: TrouverUneMesseChurch
                                           ) -> tuple[bool | None, bool | None]:
    if trouverunemesse_church.street is None:
        print(f"Church {church.name} has no street in trouverunemesse, reloading it.")
        trouverunemesse_church = fetch_trouverunemesse_by_slug(trouverunemesse_church.slug)

    location_moderation_added = None
    name_moderation_added = None

    if church.location.y != trouverunemesse_church.location.latitude or \
            church.location.x != trouverunemesse_church.location.longitude or \
            church.address != trouverunemesse_church.street or \
            church.zipcode != trouverunemesse_church.code_postal or \
            church.city != trouverunemesse_church.commune:
        # we remove every non-validated moderation related to location
        ChurchModeration.objects.filter(
            church=church,
            category__in=[
                ChurchModeration.Category.LOCATION_NULL,
                ChurchModeration.Category.LOCATION_OUTLIER,
                ChurchModeration.Category.LOCATION_CONFLICT,
                ChurchModeration.Category.LOCATION_FROM_API
            ],
        ).exclude(status=ModerationStatus.VALIDATED).delete()

        trouverunemesse_point = Point(trouverunemesse_church.location.longitude,
                                      trouverunemesse_church.location.latitude)
        if church_location_has_been_checked_by_human(church) \
                or get_geo_distance(church.location, trouverunemesse_point) > 1000:
            add_church_moderation_if_not_exists(
                ChurchModeration(
                    church=church,
                    category=ChurchModeration.Category.LOCATION_DIFFERS,
                    source=ExternalSource.TROUVERUNEMESSE,
                    address=trouverunemesse_church.street,
                    zipcode=trouverunemesse_church.code_postal,
                    city=trouverunemesse_church.commune,
                    location=trouverunemesse_point,
                    diocese=church.parish.diocese,
                    status=ModerationStatus.TO_VALIDATE,
                )
            )
            location_moderation_added = True
        else:
            church.location = trouverunemesse_point
            church.address = trouverunemesse_church.street
            if trouverunemesse_church.code_postal:
                church.zipcode = trouverunemesse_church.code_postal
            if trouverunemesse_church.commune:
                church.city = trouverunemesse_church.commune
            church.save()
            location_moderation_added = False

    # NAME is not of top quality for now
    # if church.name != trouverunemesse_church.name:
    #     if church_name_has_been_checked_by_human(church):
    #         add_church_moderation_if_not_exists(
    #             ChurchModeration(
    #                 church=church,
    #                 category=ChurchModeration.Category.NAME_DIFFERS,
    #                 source=ExternalSource.TROUVERUNEMESSE,
    #                 name=trouverunemesse_church.name,
    #                 diocese=church.parish.diocese
    #             )
    #         )
    #         name_moderation_added = True
    #     else:
    #         church.name = trouverunemesse_church.name
    #         church.save()
    #         name_moderation_added = False

    return location_moderation_added, name_moderation_added
