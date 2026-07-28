"""Resolve a recorded `AutocompleteHit` to the Website it points at.

Shared by the tuning replay (`autocomplete_replay_service`, which needs the skip reason to
report why a hit was dropped) and by `popularity_service` (which only needs the website), so the
two can never disagree on what a recorded pick refers to.

The lookup dicts are built once per instance: a caller iterating over many hits pays one query
per model. Pass `item_uuids` to restrict them to the hits actually being resolved — the replay
walks the whole table and wants everything, popularity only looks at a two-week slice.
"""
from typing import Iterable
from uuid import UUID

from registry.models import Church, Parish, Website

# Item types that point at a website. 'municipality' hits point at a City and are ignored here.
WEBSITE_ITEM_TYPES = ('parish', 'church')


def parse_uuid(raw: str | None) -> UUID | None:
    """`AutocompleteHit.item_uuid` is a CharField, so it can hold anything."""
    try:
        return UUID(raw)
    except (ValueError, TypeError, AttributeError):
        return None


class AutocompleteHitResolver:
    def __init__(self, item_uuids: Iterable[str] | None = None):
        parishes = Parish.objects.select_related('website')
        websites = Website.objects.all()
        churches = Church.objects.select_related('parish__website')
        if item_uuids is not None:
            wanted = [parsed for parsed in map(parse_uuid, item_uuids) if parsed is not None]
            parishes = parishes.filter(uuid__in=wanted)
            websites = websites.filter(uuid__in=wanted)
            churches = churches.filter(uuid__in=wanted)

        self.parish_by_uuid = {str(p.uuid): p for p in parishes}
        self.website_by_uuid = {str(w.uuid): w for w in websites}
        self.church_by_uuid = {str(c.uuid): c for c in churches}

    def resolve_target(self, item_type: str, item_uuid: str | None
                       ) -> tuple[Parish | Website | Church | None, str | None]:
        """The entity the pick designates, and the website it belongs to.

        Returns (target, skip_reason) — exactly one of the two is None. Popularity credits the
        target itself, so a church pick must stay on the church rather than climb to its website.
        """
        if item_type == 'parish':
            # Parish and Website results are both displayed as type='parish', so item_uuid is a
            # Parish uuid for some hits and a Website uuid for others: try both.
            target = self.parish_by_uuid.get(item_uuid) or self.website_by_uuid.get(item_uuid)
            if target is None or self._website_of(target) is None:
                return None, 'parish-uuid-not-found'
        elif item_type == 'church':
            target = self.church_by_uuid.get(item_uuid)
            if target is None or self._website_of(target) is None:
                return None, 'church-uuid-not-found'
        else:
            return None, f'unknown-type-{item_type}'

        if not self._website_of(target).is_active:
            return None, 'website-now-inactive'
        return target, None

    def resolve_website(self, item_type: str, item_uuid: str | None
                        ) -> tuple[Website | None, str | None]:
        """The website the pick leads to — what the replay needs to build its target URL."""
        target, reason = self.resolve_target(item_type, item_uuid)
        return (None, reason) if target is None else (self._website_of(target), None)

    @staticmethod
    def _website_of(target: Parish | Website | Church) -> Website | None:
        if isinstance(target, Website):
            return target
        if isinstance(target, Parish):
            return target.website
        return target.parish.website
