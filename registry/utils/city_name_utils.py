import re

from scheduling.utils.string_search import normalize_content, unhyphen_content


def normalize_city_name(name: str) -> str:
    """Python mirror of the City.name_norm generated column.

    Postgres computes `replace(replace(lower(immutable_unaccent(name)), '-', ' '), '''', ' ')`.
    Both must stay in sync, otherwise the query term will not match the indexed column.
    """
    return unhyphen_content(normalize_content(name)).replace("'", ' ')


def slugify_city_name(name: str) -> str:
    """URL slug of a commune name: no diacritics, every separator becomes a single hyphen.

    'L'Épine-aux-Bois' -> 'l-epine-aux-bois', 'Pont-d'Ain' -> 'pont-d-ain'.
    The second lower() is not redundant: unidecode maps some lowercase characters to uppercase
    ('ß' -> 'SS'), which the [^a-z0-9] class would otherwise strip.
    """
    slug = re.sub(r'[^a-z0-9]+', '-', normalize_content(name).lower()).strip('-')
    if not slug:
        raise ValueError(f'city name {name!r} has no slug')

    return slug
