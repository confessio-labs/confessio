"""Introspection and recovery for django-background-tasks rows.

A worker killed mid-task (deploy restart — see `restart background_main` in the Ansible deploy
role — or an OOM kill against the unit's MemoryMax) leaves its Task row locked by a PID that no
longer exists. django-background-tasks only reclaims such a row after MAX_RUN_TIME, so the work
sits untouched for 40 minutes. These helpers detect that case from the worker PID itself, which
is what `unlock_dead_tasks` (cron, every minute) and the copilot UI both need.
"""
import os
from datetime import datetime, timedelta

from background_task.models import Task
from django.db.models import Q
from django.utils import timezone

from core.settings import MAX_RUN_TIME

# Only consider a lock stale once it is this old, so we never race a worker that has just claimed
# a row but not yet started reporting.
UNLOCK_GRACE = timedelta(seconds=60)
# How often the unlock_dead_tasks cron runs (ansible/prod/roles/cron/tasks/02_commands.yml): a lock
# becomes eligible after UNLOCK_GRACE, and is actually cleared within one more period.
UNLOCK_PERIOD = timedelta(seconds=60)


class RunState:
    """How an in-flight task is doing, as reported to the UI."""
    RUNNING = 'running'      # locked by a live worker, or queued and about to start
    BLOCKED = 'blocked'      # its worker died, or it was rescheduled: it will be retried later
    LOST = 'lost'            # no task row at all — the run is gone for good


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


def unlock_dead_tasks() -> int:
    """Release the locks of tasks nobody is working on any more, so a worker picks them up again.

    Two cases, same cure: the worker process is gone (the common one — a deploy restarted it), or
    it is alive but has held the lock for longer than MAX_RUN_TIME, i.e. it is hung.
    """
    now = timezone.now()
    dead = [task.pk for task in Task.objects.filter(locked_at__lte=now - UNLOCK_GRACE)
            if not is_worker_alive(task.locked_by)]
    return Task.objects.filter(
        Q(pk__in=dead) | Q(locked_at__lte=now - timedelta(seconds=MAX_RUN_TIME))
    ).update(locked_at=None, locked_by=None)


def get_run_state(task_params_needle: str) -> tuple[str, datetime | None]:
    """Describe the task whose params contain `task_params_needle` (typically an object uuid).

    Returns its RunState and, when blocked, the moment it is expected to be retried.
    """
    task = Task.objects.filter(task_params__contains=task_params_needle).order_by('run_at').first()
    if task is None:
        return RunState.LOST, None
    if task.run_at > timezone.now():
        # Rescheduled after a failure: nothing will happen before run_at.
        return RunState.BLOCKED, task.run_at
    if task.locked_at and not is_worker_alive(task.locked_by):
        return RunState.BLOCKED, task.locked_at + UNLOCK_GRACE + UNLOCK_PERIOD
    return RunState.RUNNING, None
