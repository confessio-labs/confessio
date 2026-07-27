from datetime import timedelta

from background_task.models import Task
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.settings import MAX_RUN_TIME


class TaskStatus(models.TextChoices):
    ENQUEUED = 'enqueued'
    IN_PROGRESS = 'in_progress'


def get_task_status(task: Task, fresh_lock_after) -> TaskStatus:
    """IN_PROGRESS = a worker holds a fresh lock, ENQUEUED = only queued."""
    is_running = task.locked_by is not None and task.locked_at is not None \
        and task.locked_at > fresh_lock_after
    return TaskStatus.IN_PROGRESS if is_running else TaskStatus.ENQUEUED


def get_fresh_lock_after():
    return timezone.now() - timedelta(seconds=MAX_RUN_TIME)


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

    fresh_lock_after = get_fresh_lock_after()
    status_by_value: dict[str, TaskStatus] = {}
    for task in Task.objects.filter(params_filter, task_name=task_name):
        args, _ = task.params()
        status = get_task_status(task, fresh_lock_after)
        for value in param_values:
            if value in args:  # match this row to the requested value(s)
                # IN_PROGRESS wins if several rows exist for one value
                if status_by_value.get(value) != TaskStatus.IN_PROGRESS:
                    status_by_value[value] = status
    return status_by_value


def get_task_status_by_first_arg(task_name: str) -> dict[str, TaskStatus]:
    """Map the first positional arg of every pending/running task with this task_name to its
    TaskStatus.

    Unlike get_task_status_by_param, the candidate values are not known upfront. background_task
    deletes rows on success, so the queue only holds pending/running work: scanning every row of
    a single task_name is cheap.
    """
    fresh_lock_after = get_fresh_lock_after()
    status_by_arg: dict[str, TaskStatus] = {}
    for task in Task.objects.filter(task_name=task_name):
        args, _ = task.params()
        if not args:
            continue
        first_arg = str(args[0])
        status = get_task_status(task, fresh_lock_after)
        # IN_PROGRESS wins if several rows exist for one value
        if status_by_arg.get(first_arg) != TaskStatus.IN_PROGRESS:
            status_by_arg[first_arg] = status
    return status_by_arg
