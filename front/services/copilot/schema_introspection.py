"""Compact description of the database schema, fed to the copilot agent so it can author
read-only SQL. Generated from the Django models (apps.get_models()) and cached."""
from functools import lru_cache

from django.apps import apps

# Apps whose tables are relevant for the copilot. We skip Django internals / background_task /
# admin / sessions noise to keep the schema prompt small.
RELEVANT_APP_LABELS = {
    'registry', 'crawling', 'fetching', 'scheduling', 'attaching', 'front', 'core',
}


def _column_descriptor(field) -> str:
    parts = [field.column, field.get_internal_type()]
    if field.is_relation and field.related_model is not None:
        parts.append(f'-> {field.related_model._meta.db_table}')
    if field.primary_key:
        parts.append('PK')
    if getattr(field, 'unique', False) and not field.primary_key:
        parts.append('unique')
    if field.null:
        parts.append('null')
    return ' '.join(parts)


@lru_cache(maxsize=1)
def get_schema_text() -> str:
    """One line per table: `table_name(col type [-> fk] [flags], ...)`."""
    lines = []
    for model in sorted(apps.get_models(), key=lambda m: m._meta.db_table):
        if model._meta.app_label not in RELEVANT_APP_LABELS:
            continue
        if model._meta.db_table.startswith('historical') \
                or '_history' in model._meta.db_table:
            # Skip django-simple-history mirror tables; they double the schema for little value.
            continue
        cols = [_column_descriptor(f) for f in model._meta.concrete_fields]
        lines.append(f'{model._meta.db_table}({", ".join(cols)})')
    return '\n'.join(lines)


def describe_table(table_name: str) -> str:
    """Full column list for a single table (by db_table name), or an error message."""
    for model in apps.get_models():
        if model._meta.db_table == table_name:
            cols = [_column_descriptor(f) for f in model._meta.concrete_fields]
            return f'{table_name}:\n' + '\n'.join(f'  - {c}' for c in cols)
    return f"No table named '{table_name}'. Call describe_schema() to list available tables."
