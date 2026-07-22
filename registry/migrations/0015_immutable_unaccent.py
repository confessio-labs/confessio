from django.contrib.postgres.operations import TrigramExtension, UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('registry', '0014_alter_church_city_alter_church_zipcode_and_more'),
    ]

    operations = [
        # Both are `CREATE EXTENSION IF NOT EXISTS`: unaccent is already installed, pg_trgm is not.
        UnaccentExtension(),
        TrigramExtension(),
        migrations.RunSQL(
            sql="""
                CREATE OR REPLACE FUNCTION immutable_unaccent(text)
                RETURNS text
                LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
                AS $$ SELECT unaccent('unaccent', $1) $$;
            """,
            reverse_sql='DROP FUNCTION IF EXISTS immutable_unaccent(text);',
        ),
    ]
