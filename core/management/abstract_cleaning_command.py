from typing import Type

from django.db.models import Q, Model

from core.management.abstract_command import AbstractCommand


class AbstractCleaningCommand(AbstractCommand):
    HISTORY_DELETE_BATCH_SIZE = 5000

    def delete_objects(self, objects):
        counter = 0
        for obj in objects:
            obj.delete()
            counter += 1
        return counter

    def clean_history(self, model: Type[Model], history_model: Type[Model]):
        self.info(f'Starting cleaning {model.__name__} history items')
        query = history_model.objects.filter(
            ~Q(uuid__in=model.objects.values_list('uuid', flat=True)))
        counter = query.count()
        query.delete()
        self.success(
            f'Done removing {counter} orphan {model.__name__} history items')

    @staticmethod
    def get_changed_fields(fields_to_consider: set[str], old, new):
        """Return the set of fields that differ between two records."""
        diff = set()
        for field in fields_to_consider:
            if getattr(old, field) != getattr(new, field):
                diff.add(field)
        return diff

    def delete_history_items(self, history_model: Type[Model],
                             history_ids: list[int]):
        if not history_ids:
            return

        history_model.objects.filter(history_id__in=history_ids).delete()

    def delete_irrelevant_history(
            self, model: Type[Model], fields_to_ignore: set[str]):
        total_deleted = 0
        self.info(
            f'Starting deleting irrelevant {model.__name__} history items')

        fields = {f.name for f in model._meta.fields}
        attname_by_name = {f.name: f.attname for f in model._meta.fields}
        # Compare raw column values: reading a foreign key by its field name would fetch
        # the related object, one query per field per history item.
        attnames_to_consider = {attname_by_name[name]
                                for name in fields - fields_to_ignore}
        # Ignored fields are never read, so they stay out of the query.
        fields_to_defer = fields_to_ignore & fields

        history_model = model.history.model
        history_ids_to_delete = []

        for obj in model.objects.only('pk').iterator():
            history = list(obj.history.order_by('history_date')
                           .defer(*fields_to_defer))

            if len(history) < 2:
                continue

            for prev, current in zip(history, history[1:]):
                if current.history_type in ['+', '-']:
                    continue

                changed_fields = self.get_changed_fields(
                    attnames_to_consider, prev, current)

                if not changed_fields:
                    history_ids_to_delete.append(current.history_id)
                    total_deleted += 1

            if len(history_ids_to_delete) >= self.HISTORY_DELETE_BATCH_SIZE:
                self.delete_history_items(history_model, history_ids_to_delete)
                history_ids_to_delete = []

        self.delete_history_items(history_model, history_ids_to_delete)

        self.success(
            f"Deleted {total_deleted} irrelevant "
            f"{model.__name__} history items.")
