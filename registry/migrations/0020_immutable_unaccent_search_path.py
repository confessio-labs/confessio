from django.db import migrations

# A SQL function body is an opaque string, resolved against the CALLER's search_path at execution
# time. `pg_dump` emits `set_config('search_path', '', false)` at the top of its output, so the
# unqualified `unaccent` of migration 0015 is invisible during a `dbrestore` and every restore dies
# as soon as psql COPYs into a table whose `name_norm` generated column has to be recomputed.
# Schema-qualifying the body fixes it. `regdictionary` needs no qualification: pg_catalog is always
# implicitly part of the search_path.
#
# CREATE OR REPLACE (rather than DROP + CREATE) keeps the function OID, so the `name_norm` generated
# columns and their gin_trgm_ops indexes stay valid: no rewrite, no reindex, no recompute. The
# result is byte-identical to the previous definition.
NEW_SQL = """
    CREATE OR REPLACE FUNCTION public.immutable_unaccent(text)
    RETURNS text
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;
"""

OLD_SQL = """
    CREATE OR REPLACE FUNCTION public.immutable_unaccent(text)
    RETURNS text
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    AS $$ SELECT unaccent('unaccent', $1) $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('registry', '0019_remove_historicalwebsite_is_best_diocese_hit_and_more'),
    ]

    operations = [
        migrations.RunSQL(sql=NEW_SQL, reverse_sql=OLD_SQL),
    ]
