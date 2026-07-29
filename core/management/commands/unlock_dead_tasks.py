from core.management.abstract_command import AbstractCommand
from core.services.background_task_service import unlock_dead_tasks


class Command(AbstractCommand):
    help = "Unlock tasks whose worker process is gone, so a live worker picks them up again"

    def handle(self, *args, **options):
        self.info(f'Starting unlocking dead tasks...')
        # django-background-tasks never unlocks a task whose worker crashed: it just waits for
        # MAX_RUN_TIME (40 min). Detecting the dead worker directly brings that down to ~2 min.
        count = unlock_dead_tasks()
        self.success(f'Finished unlocking dead tasks, {count} unlocked')
