from core.management.abstract_command import AbstractCommand
from front.services.search.popularity_service import update_popularity


class Command(AbstractCommand):
    # Now updates churches and parishes too, but keeps its name so the prod cron entry in
    # ansible/prod/roles/cron/tasks/02_commands.yml does not have to be renamed and re-created.
    help = "Update popularity of churches, parishes and websites based on recent hits"

    def handle(self, *args, **options):
        self.info(f'Starting computing popularity')
        update_popularity()
        self.success(f'Finished computing popularity')
