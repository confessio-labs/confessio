from datetime import timedelta

from background_task.models import Task
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.settings import MAX_RUN_TIME


class TaskStatus(models.TextChoices):
    ENQUEUED = 'enqueued'
    IN_PROGRESS = 'in_progress'


def get_task_status_by_param(task_name: str, param_values: set[str]) -> dict[str, TaskStatus]:
    """For each param value found in a pending/running task with this task_name, map it to its
    TaskStatus (IN_PROGRESS = a worker holds a fresh lock, ENQUEUED = only queued).

    Filters at the DB level so only rows mentioning one of the requested values are fetched,
    never the whole queue (task_params is JSON text -> LIKE '%value%' per value).
    """
    if not param_values:
        return {}

    params_filter = Q()
    for value in param_values:
        params_filter |= Q(task_params__contains=value)

    fresh_lock_after = timezone.now() - timedelta(seconds=MAX_RUN_TIME)
    status_by_value: dict[str, TaskStatus] = {}
    for task in Task.objects.filter(params_filter, task_name=task_name):
        args, _ = task.params()
        is_running = task.locked_by is not None and task.locked_at is not None \
            and task.locked_at > fresh_lock_after
        status = TaskStatus.IN_PROGRESS if is_running else TaskStatus.ENQUEUED
        for value in param_values:
            if value in args:  # match this row to the requested value(s)
                # IN_PROGRESS wins if several rows exist for one value
                if status_by_value.get(value) != TaskStatus.IN_PROGRESS:
                    status_by_value[value] = status
    return status_by_value
