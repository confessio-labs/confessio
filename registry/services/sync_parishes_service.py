from abc import ABC, abstractmethod
from statistics import mean
from typing import Optional

from django.contrib.gis.geos import Point

from crawling.public_workflow import crawling_redirects_to_other_url
from registry.models import Parish, Diocese, ParishModeration, Website, ExternalSource
from registry.models.base_moderation_models import ModerationStatus
from registry.services.parish_website_service import save_website_of_parish
from registry.utils.geo_utils import get_geo_distance
from registry.utils.string_utils import get_string_similarity


####################
# PARISH RETRIEVAL #
####################

class ParishRetriever(ABC):
    @property
    @abstractmethod
    def source(self) -> ExternalSource:
        pass

    @abstractmethod
    def retrieve_parish(self, external_parish: Parish) -> Optional[Parish]:
        pass

    @abstractmethod
    def parish_exists_in_list(self, parish: Parish,
                              external_parishes: list[Parish]) -> bool:
        pass

    @abstractmethod
    def is_same_parish_set(self, parish_set1: Optional[set[Parish]],
                           parish_set2: Optional[set[Parish]]) -> bool:
        pass


class MessesinfoParishRetriever(ParishRetriever):
    source = ExternalSource.MESSESINFO

    def retrieve_parish(self, external_parish: Parish) -> Optional[Parish]:
        try:
            return Parish.objects.get(
                messesinfo_community_id=external_parish.messesinfo_community_id)
        except Parish.DoesNotExist:
            return None

    def parish_exists_in_list(self, parish: Parish,
                              external_parishes: list[Parish]) -> bool:
        for external_parish in external_parishes:
            if external_parish.messesinfo_community_id == parish.messesinfo_community_id:
                return True

        return False

    def is_same_parish_set(self, parish_set1: Optional[set[Parish]],
                           parish_set2: Optional[set[Parish]]) -> bool:
        return set([p.messesinfo_community_id for p in (parish_set1 or set())]) \
            == set([p.messesinfo_community_id for p in (parish_set2 or set())])


###############
# PARISH SYNC #
###############

def add_parish_moderation_if_not_exists(parish_moderation: ParishModeration,
                                        parish_retriever: ParishRetriever,
                                        similar_parishes: set[Parish] = None):
    try:
        existing_moderation = ParishModeration.objects.get(
            parish=parish_moderation.parish,
            category=parish_moderation.category,
            source=parish_moderation.source
        )
        if existing_moderation.name != parish_moderation.name \
                or not is_same_website(existing_moderation.website, parish_moderation.website) \
                or not parish_retriever.is_same_parish_set(
                    set(existing_moderation.similar_parishes.all()), similar_parishes):
            existing_moderation.delete()
            parish_moderation.save()
            if similar_parishes:
                parish_moderation.similar_parishes.set(similar_parishes)
    except ParishModeration.DoesNotExist:
        parish_moderation.save()
        if similar_parishes:
            parish_moderation.similar_parishes.set(similar_parishes)


def update_parish(parish: Parish,
                  external_parish: Parish,
                  parish_retriever: ParishRetriever):
    # Check name
    if (parish.name != external_parish.name
            and all(p.name != external_parish.name for p in parish.history.all())):
        add_parish_moderation_if_not_exists(ParishModeration(
            parish=parish, category=ParishModeration.Category.NAME_DIFFERS,
            source=parish_retriever.source, name=external_parish.name,
            diocese=parish.diocese,
            status=ModerationStatus.TO_VALIDATE,
        ), parish_retriever)

    # Check website
    if external_parish.website:
        if parish.website \
                and crawling_redirects_to_other_url(external_parish.website.home_url,
                                                    parish.website.home_url):
            return

        try:
            website = Website.objects.get(home_url=external_parish.website.home_url)
        except Website.DoesNotExist:
            website = external_parish.website
            website.is_active = False
            website.save()

        if not parish.website:
            website.is_active = True
            website.save()
            parish.website = website
            parish.save()
        else:
            add_parish_moderation_if_not_exists(ParishModeration(
                parish=parish, category=ParishModeration.Category.WEBSITE_DIFFERS,
                source=parish_retriever.source, website=website,
                diocese=parish.diocese,
                status=ModerationStatus.TO_VALIDATE,
            ), parish_retriever)


def look_for_similar_parishes_by_name(external_parish: Parish,
                                      diocese_parishes: list[Parish]) -> set[Parish]:
    # get the distance between the external parish and all the parishes in the diocese
    similarity_tuples = zip(map(lambda p: get_string_similarity(external_parish.name, p.name),
                                diocese_parishes), diocese_parishes)
    # keep only the three most similar parishes
    closest_parishes = sorted(similarity_tuples, key=lambda t: t[0], reverse=True)[:3]
    if not closest_parishes:
        return set()

    _, similar_parishes = zip(*closest_parishes)

    return set(similar_parishes)


def look_for_similar_parishes_by_distance(
        external_parish: Parish,
        diocese_parishes: list[Parish],
        parish_barycentre_by_uuid: dict[str, Point]) -> set[Parish]:
    external_parish_barycentre = get_parish_barycentre(external_parish)
    if not external_parish_barycentre:
        return set()

    # get the distance between the external parish and all the parishes in the diocese
    distance_tuples = []
    for parish in diocese_parishes:
        if parish.uuid not in parish_barycentre_by_uuid:
            continue

        parish_barycentre = parish_barycentre_by_uuid[parish.uuid]
        geo_distance = get_geo_distance(external_parish_barycentre, parish_barycentre)

        distance_tuples.append((geo_distance, parish))

    # keep only the three closest parishes
    closest_parishes = sorted(distance_tuples, key=lambda t: t[0], reverse=False)[:3]
    if not closest_parishes:
        return set()

    _, similar_parishes = zip(*closest_parishes)

    return set(similar_parishes)


def get_parish_barycentre(parish: Parish) -> Optional[Point]:
    churches_points = [c.location for c in parish.churches.all() if c.location]
    if not churches_points:
        return None

    return Point(mean(map(lambda p: p.x, churches_points)),
                 mean(map(lambda p: p.y, churches_points)))


def get_parish_barycentre_by_uuid(diocese_parishes: list[Parish]) -> dict[str, Point]:
    parish_barycentre_by_uuid = {}
    for parish in diocese_parishes:
        parish_barycentre = get_parish_barycentre(parish)
        if not parish_barycentre:
            continue

        parish_barycentre_by_uuid[parish.uuid] = parish_barycentre

    return parish_barycentre_by_uuid


def look_for_similar_parishes(external_parish: Parish,
                              diocese_parishes: list[Parish],
                              parish_barycentre_by_uuid: dict[str, Point]) -> set[Parish]:
    similar_parishes = set()

    # 1. Check if there is a parish with the same website
    if external_parish.website:
        similar_parishes |= set(Parish.objects.filter(
            website__home_url=external_parish.website.home_url).all())

    # 2. Check if there is a parish with the same name
    similar_parishes |= look_for_similar_parishes_by_name(external_parish, diocese_parishes)

    # 3. Check for the closest parishes
    similar_parishes |= look_for_similar_parishes_by_distance(external_parish, diocese_parishes,
                                                              parish_barycentre_by_uuid)

    return similar_parishes


def sync_parishes(external_parishes: list[Parish],
                  diocese: Diocese,
                  parish_retriever: ParishRetriever,
                  allow_no_url: bool = False,
                  alert_on_new: bool = False,
                  alert_on_delete: bool = False,
                  ):
    # get all parishes in the diocese
    diocese_parishes = list(diocese.parishes.all())

    # get parish barycentre
    parish_barycentre_by_uuid = get_parish_barycentre_by_uuid(diocese_parishes)

    print('looping through external parishes')
    for external_parish in external_parishes:
        confessio_parish = parish_retriever.retrieve_parish(external_parish)
        if confessio_parish:
            # Parish already exists, we update it
            update_parish(confessio_parish, external_parish, parish_retriever)
        else:
            # Parish does not exist, finding similar parishes or create it

            if not allow_no_url and not external_parish.website:
                # We don't really care if there is a new parish without a website
                continue

            similar_parishes = look_for_similar_parishes(external_parish,
                                                         diocese_parishes,
                                                         parish_barycentre_by_uuid)

            save_parish(external_parish)

            if alert_on_new:
                add_parish_moderation_if_not_exists(ParishModeration(
                    parish=external_parish,
                    category=ParishModeration.Category.ADDED_PARISH,
                    source=parish_retriever.source,
                    diocese=diocese,
                    status=ModerationStatus.TO_VALIDATE,
                ), parish_retriever, similar_parishes=similar_parishes)

    if alert_on_delete:
        print('looping on diocese parishes')
        for parish in diocese_parishes:
            if not parish_retriever.parish_exists_in_list(parish, external_parishes):
                add_parish_moderation_if_not_exists(ParishModeration(
                    parish=parish,
                    category=ParishModeration.Category.DELETED_PARISH,
                    source=parish_retriever.source,
                    diocese=diocese,
                    status=ModerationStatus.TO_VALIDATE,
                ), parish_retriever)


###############
# PARISH SAVE #
###############

def is_same_website(website1: Optional[Website], website2: Optional[Website]):
    if website1 is None and website2 is None:
        return True

    if website1 is None or website2 is None:
        return False

    return website1.home_url == website2.home_url


def save_parish(parish: Parish):
    parish.website = save_website_of_parish(parish)
    parish.save()
