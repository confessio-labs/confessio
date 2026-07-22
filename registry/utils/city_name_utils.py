from scheduling.utils.string_search import normalize_content, unhyphen_content


def normalize_city_name(name: str) -> str:
    """Python mirror of the City.name_norm generated column.

    Postgres computes `replace(replace(lower(immutable_unaccent(name)), '-', ' '), '''', ' ')`.
    Both must stay in sync, otherwise the query term will not match the indexed column.
    """
    return unhyphen_content(normalize_content(name)).replace("'", ' ')
