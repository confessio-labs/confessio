"""Recompute Website.nb_recent_hits and Website.is_best_diocese_hit from recent traffic.

Popularity is the total number of requests attributable to a website over the last
POPULARITY_WINDOW_DAYS days, summed over every path that names an entity: the website pages
themselves, the per-church API endpoint (folded into the church's website), and explicit
autocomplete picks.

Not every request can be attributed: /front/api/search is a bounding-box query and names no
entity, yet it is by far the busiest endpoint. report_attribution_coverage() prints the share of
UUID-bearing requests that were actually counted, so a newly added route that nobody wired in
here shows up in the nightly log instead of silently deflating popularity.
"""
import re
from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import Count, Q
from django.utils.timezone import make_aware
from request.models import Request

from front.models import AutocompleteHit
from front.services.search.autocomplete_hit_service import (WEBSITE_ITEM_TYPES,
                                                            AutocompleteHitResolver, parse_uuid)
from front.utils.popularity_constants import POPULARITY_WINDOW_DAYS
from registry.models import Church, Parish, Website
from scheduling.models import IndexEvent

# Pages that name a website in their third path segment, e.g. /paroisse/<uuid>. The prefix match
# also covers deeper paths like /paroisse/<uuid>/upload_image, which is intended.
WEBSITE_PATH_PREFIXES = (
    '/paroisse/',
    '/website_churches/',
    '/website_sources/',
    '/website_events/',
)
WEBSITE_UUID_PATH_INDEX = 2

# The Next.js front renders church pages itself and fetches their content from here, so this is
# the only trace a church view leaves in the request log — and it is the largest single source.
CHURCH_API_PATH_PREFIX = '/front/api/church/'
CHURCH_UUID_PATH_INDEX = 4

UUID_PATTERN = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'


def path_segment(path: str, index: int) -> str | None:
    """Segment `index` of a request path, query string stripped.

    FullPathRequestMiddleware stores get_full_path(), so the query string is part of `path`.
    """
    segments = path.split('?')[0].split('/')
    return segments[index] if len(segments) > index else None


def paths_starting_with(*prefixes: str) -> Q:
    path_filter = Q()
    for prefix in prefixes:
        path_filter |= Q(path__startswith=prefix)
    return path_filter


def count_requests_by_uuid(path_filter: Q, since: datetime, uuid_path_index: int
                           ) -> tuple[dict[UUID, int], int]:
    """Count matching requests per entity uuid. Returns (counts, nb_unparseable).

    Postgres groups identical paths, then Python extracts the uuid: the grouping keeps the
    transfer small, and the parsing is not expressible in the ORM.
    """
    counts: dict[UUID, int] = {}
    nb_unparseable = 0
    rows = Request.objects.filter(path_filter, time__gt=since) \
        .values('path').annotate(nb=Count('id')).iterator()
    for row in rows:
        entity_uuid = parse_uuid(path_segment(row['path'], uuid_path_index))
        if entity_uuid is None:
            nb_unparseable += row['nb']
            continue
        counts[entity_uuid] = counts.get(entity_uuid, 0) + row['nb']
    return counts, nb_unparseable


def drop_unknown_uuids(model: type, count_by_uuid: dict[UUID, int]) -> int:
    """Discard counts whose uuid names no live row. Returns the nb of discarded views.

    A path can point at an entity that has since been deleted; keeping it would inflate the
    'with traffic' totals and the attribution coverage.
    """
    known = set(model.objects.filter(uuid__in=count_by_uuid).values_list('uuid', flat=True))
    nb_dropped = 0
    for entity_uuid in [u for u in count_by_uuid if u not in known]:
        nb_dropped += count_by_uuid.pop(entity_uuid)
    return nb_dropped


def add_autocomplete_picks(since: datetime, count_by_uuid_per_model: dict[type, dict[UUID, int]]
                           ) -> tuple[int, int]:
    """Credit each explicit autocomplete pick to the entity it designates.

    Returns (nb_added, nb_unattributed). A pick lands on whatever the user actually chose — a
    Church pick stays on the church — so this is the only source Parish popularity ever gets.
    Municipality picks are deliberately absent from WEBSITE_ITEM_TYPES: a city's standing comes
    from its population alone, and picking it must never make it more popular.
    """
    hits = list(AutocompleteHit.objects.filter(
        created_at__gt=since, item_type__in=WEBSITE_ITEM_TYPES).exclude(item_uuid=None))
    resolver = AutocompleteHitResolver(item_uuids=[hit.item_uuid for hit in hits])

    nb_added = nb_unattributed = 0
    for hit in hits:
        target, _ = resolver.resolve_target(hit.item_type, hit.item_uuid)
        if target is None:
            nb_unattributed += 1
            continue
        counts = count_by_uuid_per_model[type(target)]
        counts[target.uuid] = counts.get(target.uuid, 0) + 1
        nb_added += 1
    return nb_added, nb_unattributed


def persist_counts(model: type, count_by_uuid: dict[UUID, int]) -> tuple[int, int]:
    """Write one model's counts and zero out every other row. Returns (nb_updated, nb_reset).

    bulk_update deliberately: it writes no simple_history row and leaves `updated_at` alone.
    A nightly counter is not an edit to the entity, and `updated_at` is the cursor of the public
    /websites API (front/api.py), which would otherwise report every popular row as modified
    every night.
    """
    to_update = []
    for obj in model.objects.filter(uuid__in=count_by_uuid):
        count = count_by_uuid[obj.uuid]
        if count != obj.nb_recent_hits:
            obj.nb_recent_hits = count
            to_update.append(obj)
    model.objects.bulk_update(to_update, ['nb_recent_hits'])

    # Rows that lost all their traffic are absent from the counts, so they need an explicit
    # reset: without it a stale value survives forever.
    nb_reset = model.objects.exclude(uuid__in=count_by_uuid) \
        .filter(nb_recent_hits__gt=0).update(nb_recent_hits=0)
    return len(to_update), nb_reset


def update_best_diocese_hits(count_by_website_uuid: dict[UUID, int]) -> int:
    """Flag the most visited website of each diocese. Returns the nb of flagged websites."""
    websites_by_uuid = {w.uuid: w for w in Website.objects.filter(uuid__in=count_by_website_uuid)}
    # Website.get_diocese() reads the first of its parishes, one query per website; the same
    # mapping in bulk, ordered so the pick stays deterministic.
    diocese_by_website_uuid: dict[UUID, UUID] = {}
    for website_uuid, diocese_uuid in Parish.objects \
            .filter(website__uuid__in=count_by_website_uuid) \
            .order_by('uuid').values_list('website_id', 'diocese_id'):
        diocese_by_website_uuid.setdefault(website_uuid, diocese_uuid)

    count_by_diocese: dict[UUID, dict[Website, int]] = {}
    for website_uuid, count in count_by_website_uuid.items():
        diocese_uuid = diocese_by_website_uuid.get(website_uuid)
        website = websites_by_uuid.get(website_uuid)
        if diocese_uuid is None or website is None:
            # A website with no parish belongs to no diocese.
            continue
        count_by_diocese.setdefault(diocese_uuid, {})[website] = count

    winner_uuids = {get_best_website_for_diocese(count_by_website).uuid
                    for count_by_website in count_by_diocese.values()}

    # One update for every diocese at once. Resetting inside the loop would clear the winners of
    # the dioceses already processed, leaving a single flagged website in the whole table.
    Website.objects.filter(is_best_diocese_hit=True).exclude(uuid__in=winner_uuids) \
        .update(is_best_diocese_hit=False)
    Website.objects.filter(uuid__in=winner_uuids, is_best_diocese_hit=False) \
        .update(is_best_diocese_hit=True)
    return len(winner_uuids)


def get_best_website_for_diocese(count_by_website: dict[Website, int]) -> Website:
    websites_with_events = set(
        IndexEvent.objects.filter(church__parish__website__in=count_by_website)
        .values_list('church__parish__website_id', flat=True))
    for website, count in sorted(count_by_website.items(), key=lambda item: item[1], reverse=True):
        if website.uuid in websites_with_events:
            return website

    return max(count_by_website, key=count_by_website.get)


def report_attribution_coverage(since: datetime, nb_attributed: int) -> None:
    """Print how much UUID-bearing traffic we managed to attribute, and what we missed.

    This is the guard that would have caught the Next.js migration: when the front moved to new
    routes, the hardcoded prefixes above kept matching only the legacy pages.
    """
    known_prefixes = WEBSITE_PATH_PREFIXES + (CHURCH_API_PATH_PREFIX,)
    nb_total = 0
    nb_by_shape: dict[str, int] = {}
    rows = Request.objects.filter(time__gt=since, path__regex=UUID_PATTERN) \
        .values('path').annotate(nb=Count('id')).iterator()
    for row in rows:
        # The stored path includes the query string, so re-test the path alone: a uuid in a
        # ?next= parameter names no entity.
        path = row['path'].split('?')[0]
        if not re.search(UUID_PATTERN, path):
            continue
        nb_total += row['nb']
        if path.startswith(known_prefixes):
            continue
        shape = re.sub(UUID_PATTERN, '<uuid>', path)
        nb_by_shape[shape] = nb_by_shape.get(shape, 0) + row['nb']

    if not nb_total:
        print('No uuid-bearing request in the window')
        return

    print(f'Attributed {nb_attributed}/{nb_total} uuid-bearing requests '
          f'({nb_attributed / nb_total:.1%})')
    for shape, nb in sorted(nb_by_shape.items(), key=lambda item: item[1], reverse=True)[:10]:
        print(f'    unattributed: {shape} ({nb})')


def update_popularity():
    """Recompute the three per-entity popularity counters over the rolling window.

    Each entity keeps the traffic it earned: a church detail view credits the church, never its
    parish or its website. Folding them upwards, as this used to do, gave every church of a
    website the same popularity and made the church rankings unable to tell them apart.
    """
    since = make_aware(datetime.now() - timedelta(days=POPULARITY_WINDOW_DAYS))

    count_by_website_uuid, nb_bad_website_paths = count_requests_by_uuid(
        paths_starting_with(*WEBSITE_PATH_PREFIXES), since, WEBSITE_UUID_PATH_INDEX)
    nb_gone_website_views = drop_unknown_uuids(Website, count_by_website_uuid)
    nb_website_views = sum(count_by_website_uuid.values())

    count_by_church_uuid, nb_bad_church_paths = count_requests_by_uuid(
        paths_starting_with(CHURCH_API_PATH_PREFIX), since, CHURCH_UUID_PATH_INDEX)
    nb_gone_church_views = drop_unknown_uuids(Church, count_by_church_uuid)
    nb_church_views = sum(count_by_church_uuid.values())

    count_by_parish_uuid: dict[UUID, int] = {}
    nb_picks, nb_orphan_picks = add_autocomplete_picks(since, {
        Website: count_by_website_uuid,
        Parish: count_by_parish_uuid,
        Church: count_by_church_uuid,
    })

    print(f'{nb_website_views} website page views ({nb_bad_website_paths} with an invalid uuid,'
          f' {nb_gone_website_views} on a deleted website)')
    print(f'{nb_church_views} church api views ({nb_bad_church_paths} with an invalid uuid,'
          f' {nb_gone_church_views} on a deleted church)')
    print(f'{nb_picks} autocomplete picks ({nb_orphan_picks} unresolved)')

    for model, count_by_uuid in ((Website, count_by_website_uuid),
                                 (Parish, count_by_parish_uuid),
                                 (Church, count_by_church_uuid)):
        nb_updated, nb_reset = persist_counts(model, count_by_uuid)
        print(f'{len(count_by_uuid)} {model.__name__.lower()}s with traffic,'
              f' {nb_updated} counts changed, {nb_reset} stale counts reset to zero')

    nb_best = update_best_diocese_hits(count_by_website_uuid)
    print(f'{nb_best} dioceses with a best website')

    report_attribution_coverage(since, nb_website_views + nb_church_views)
