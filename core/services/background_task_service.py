import os
from datetime import datetime, timedelta

from background_task.models import Task
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.settings import MAX_RUN_TIME

# Only treat a lock as stale once it is this old, so we never race a worker that has just claimed
# a row but not yet started reporting.
UNLOCK_GRACE = timedelta(seconds=60)
# How often the unlock_dead_tasks cron runs (ansible/prod/roles/cron/tasks/02_commands.yml): a lock
# becomes eligible after UNLOCK_GRACE, and is actually cleared within one more period.
UNLOCK_PERIOD = timedelta(seconds=60)


class TaskStatus(models.TextChoices):
    ENQUEUED = 'enqueued'        # accepted, but no worker has picked it up yet
    IN_PROGRESS = 'in_progress'  # a live worker holds a fresh lock: work is actually happening
    BLOCKED = 'blocked'          # its worker died, or it was rescheduled: retried later
    LOST = 'lost'                # no task row at all — the run is gone for good


def is_worker_alive(locked_by: str | None) -> bool:
    """Whether the process that locked a task still exists on this host.

    Not Task.locked_by_pid_running(): its bare `except` reads an EPERM from os.kill (the process
    exists but belongs to another user) as "dead", which would unlock a task that is still running.
    """
    if not locked_by:
        return False
    try:
        os.kill(int(locked_by), 0)
    except PermissionError:
        return True  # it exists, we just may not signal it
    except (OSError, ValueError):
        return False
    return True


def get_task_status(task: Task, fresh_lock_after) -> TaskStatus:
    """IN_PROGRESS = a live worker holds a fresh lock, ENQUEUED = only queued."""
    is_running = task.locked_at is not None and task.locked_at > fresh_lock_after \
        and is_worker_alive(task.locked_by)
    return TaskStatus.IN_PROGRESS if is_running else TaskStatus.ENQUEUED


def get_fresh_lock_after():
    return timezone.now() - timedelta(seconds=MAX_RUN_TIME)


def unlock_dead_tasks() -> int:
    """Release the locks of tasks nobody is working on any more, so a worker picks them up again.

    Two cases, same cure: the worker process is gone (the common one — a deploy restarted it, see
    `restart background_main` in the Ansible deploy role), or it is alive but has held the lock for
    longer than MAX_RUN_TIME, i.e. it is hung.
    """
    now = timezone.now()
    dead = [task.pk for task in Task.objects.filter(locked_at__lte=now - UNLOCK_GRACE)
            if not is_worker_alive(task.locked_by)]
    return Task.objects.filter(
        Q(pk__in=dead) | Q(locked_at__lte=now - timedelta(seconds=MAX_RUN_TIME))
    ).update(locked_at=None, locked_by=None)


def get_task_run_state(task_params_needle: str) -> tuple[TaskStatus, datetime | None]:
    """Describe the task whose params contain `task_params_needle` (typically an object uuid).

    Unlike get_task_status this also tells apart "will never run again" (LOST) from "waiting for a
    retry" (BLOCKED), and says when that retry is due — what a UI needs to stop showing a spinner
    for a turn nobody is working on.
    """
    task = Task.objects.filter(task_params__contains=task_params_needle).order_by('run_at').first()
    if task is None:
        return TaskStatus.LOST, None
    if task.run_at > timezone.now():
        # Rescheduled after a failure: nothing will happen before run_at.
        return TaskStatus.BLOCKED, task.run_at
    if task.locked_at is None:
        return TaskStatus.ENQUEUED, None
    if not is_worker_alive(task.locked_by):
        return TaskStatus.BLOCKED, task.locked_at + UNLOCK_GRACE + UNLOCK_PERIOD
    return TaskStatus.IN_PROGRESS, None


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
