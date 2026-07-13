from django.contrib.gis.geos import Point

from registry.models import Church, ChurchModeration, ExternalSource
from registry.models.base_moderation_models import ModerationStatus
from registry.services.church_human_service import church_location_has_been_checked_by_human
from registry.utils.annuairecatholique_utils import AnnuaireCatholiquePlace, fetch_place_by_id, \
    fetch_places
from registry.utils.geo_utils import get_geo_distance


# Above this distance (m), an annuairecatholique position differs so wildly from the church's
# current one that it almost certainly means a wrong place-match, not a real correction — keep
# staging those for human review instead of auto-applying.
MAX_AUTO_APPLY_METERS = 20_000


def add_church_moderation_if_not_exists(church_moderation: ChurchModeration):
    try:
        ChurchModeration.objects.get(
            church=church_moderation.church,
            category=church_moderation.category,
            source=church_moderation.source
        )
    except ChurchModeration.DoesNotExist:
        church_moderation.save()


def link_church_to_place(church: Church, place: AnnuaireCatholiquePlace) -> None:
    church.annuairecatholique_id = place.id
    church.annuairecatholique_business_id = place.business_id
    church.annuairecatholique_updated_at = place.updated_at
    church.save()


def sync_annuairecatholique_for_church(church: Church) -> bool | None:
    if church.annuairecatholique_id:
        place = fetch_place_by_id(str(church.annuairecatholique_id))
        if not place:
            print(f"Could not find annuairecatholique place for id "
                  f'{church.annuairecatholique_id}')
            return None
        return sync_annuairecatholique_location_and_city(church, place)

    if church.wikidata_id:
        places, _ = fetch_places(wikidata_id=church.wikidata_id)
        if not places:
            print(f"Could not find annuairecatholique place for wikidata_id "
                  f'{church.wikidata_id}')
            return None
        place = places[0]
        link_church_to_place(church, place)
        return sync_annuairecatholique_location_and_city(church, place)

    print(f"Church {church.name} has no linkable identifier, skipping sync.")
    return None


def sync_annuairecatholique_location_and_city(church: Church, place: AnnuaireCatholiquePlace
                                              ) -> bool | None:
    if place.position is None or place.commune is None:
        return None

    new_point = Point(place.position.longitude, place.position.latitude)
    new_city = place.commune.name

    if church.location == new_point and church.city == new_city:
        return None

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

    # Auto-apply the well-sourced annuairecatholique position when a human has never curated this
    # church's location. Keep staging for review when a human HAS curated it, or when the move is
    # so large it signals a bad place-match rather than a real correction.
    location_implausible = church.location is not None \
        and get_geo_distance(church.location, new_point) > MAX_AUTO_APPLY_METERS
    if church_location_has_been_checked_by_human(church) or location_implausible:
        add_church_moderation_if_not_exists(
            ChurchModeration(
                church=church,
                category=ChurchModeration.Category.LOCATION_DIFFERS,
                source=ExternalSource.ANNUAIRECATHOLIQUE,
                address=church.address,  # preserve — API does not provide
                zipcode=church.zipcode,  # preserve — API does not provide
                city=new_city,
                location=new_point,
                diocese=church.parish.diocese,
                status=ModerationStatus.TO_VALIDATE,
            )
        )
        return True

    # Applying the correction resolves any un-validated annuairecatholique LOCATION_DIFFERS staged
    # earlier under the old 1 km guard, so it shouldn't linger as an orphan to_validate row.
    ChurchModeration.objects.filter(
        church=church,
        category=ChurchModeration.Category.LOCATION_DIFFERS,
        source=ExternalSource.ANNUAIRECATHOLIQUE,
    ).exclude(status=ModerationStatus.VALIDATED).delete()

    church.location = new_point
    church.city = new_city  # do NOT touch church.address / church.zipcode
    church.save()
    return False
