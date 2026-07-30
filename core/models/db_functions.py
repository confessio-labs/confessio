from django.db.models import Func


class ImmutableUnaccent(Func):
    """Wrapper around the SQL `immutable_unaccent()` function.

    `unaccent(text)` is STABLE, not IMMUTABLE, so it can be used neither in a generated column
    nor in an index expression. The one-argument SQL wrapper pins the dictionary and is declared
    IMMUTABLE. It is created in registry migration 0015_immutable_unaccent, and its body is
    schema-qualified in 0020_immutable_unaccent_search_path (an unqualified body breaks dbrestore,
    which runs with an empty search_path).
    """
    function = 'immutable_unaccent'
    arity = 1
