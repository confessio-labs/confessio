from django.db.models import Func


class ImmutableUnaccent(Func):
    """Wrapper around the SQL `immutable_unaccent()` function.

    `unaccent(text)` is STABLE, not IMMUTABLE, so it can be used neither in a generated column
    nor in an index expression. The one-argument SQL wrapper pins the dictionary and is declared
    IMMUTABLE. It is created in registry migration 0015_immutable_unaccent.
    """
    function = 'immutable_unaccent'
    arity = 1
