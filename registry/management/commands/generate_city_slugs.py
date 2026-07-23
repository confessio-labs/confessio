from core.management.abstract_command import AbstractCommand
from registry.services.city_service import refresh_city_slugs


class Command(AbstractCommand):
    help = "Compute and fill the slug of every city."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='only report how many slugs would change')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        self.info(f'Starting to generate city slugs{" (dry run)" if dry_run else ""}...')
        nb_cities, nb_changed = refresh_city_slugs(dry_run=dry_run)
        verb = 'would be updated' if dry_run else 'updated'
        self.success(f'Successfully computed {nb_cities} city slugs, {nb_changed} {verb}.')
