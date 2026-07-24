from datetime import timedelta

from background_task.models import Task
from django.db.models import Q
from django.utils import timezone

from core.settings import MAX_RUN_TIME


def get_locked_state_by_param(task_name: str, param_values: set[str]) -> dict[str, bool]:
    """For each param value found in a pending/running task with this task_name, map it to
    whether a worker currently holds a fresh lock (True = running, False = only enqueued).

    Filters at the DB level so only rows mentioning one of the requested values are fetched,
    never the whole queue (task_params is JSON text -> LIKE '%value%' per value).
    """
    if not param_values:
        return {}

    params_filter = Q()
    for value in param_values:
        params_filter |= Q(task_params__contains=value)

    fresh_lock_after = timezone.now() - timedelta(seconds=MAX_RUN_TIME)
    is_running_by_value: dict[str, bool] = {}
    for task in Task.objects.filter(params_filter, task_name=task_name):
        args, _ = task.params()
        is_running = task.locked_by is not None and task.locked_at is not None \
            and task.locked_at > fresh_lock_after
        for value in param_values:
            if value in args:  # match this row to the requested value(s)
                # 'running' wins if several rows exist for one value
                is_running_by_value[value] = is_running_by_value.get(value, False) or is_running
    return is_running_by_value
