from core.management.abstract_command import AbstractCommand
from registry.services.city_service import CityLocationUpdateStats, update_city_locations


def print_city_location_stats(command: AbstractCommand, stats: CityLocationUpdateStats,
                              dry_run: bool = False):
    verb = 'would be moved' if dry_run else 'moved'
    command.success(f'{stats.nb_matched}/{stats.nb_cities} cities matched an OSM admin centre, '
                    f'{stats.nb_moved} {verb} '
                    f'({stats.nb_moved_over_1km} by >1km, {stats.nb_moved_over_5km} by >5km).')
    if stats.nb_unmatched:
        command.warning(f'{stats.nb_unmatched} cities without OSM admin centre kept their '
                        f'location.')
    for insee_code, name, distance in stats.top_movers:
        command.info(f'  moved {distance / 1000:.1f}km: {name} ({insee_code})')
    if stats.failed_prefixes:
        hint = ' '.join(f'--department {p}' for p in stats.failed_prefixes)
        command.warning(f'overpass failed for some prefixes, '
                        f'rerun update_city_locations with: {hint}')


class Command(AbstractCommand):
    help = "Move every city to the OSM admin centre (town center) position of its commune."

    def add_arguments(self, parser):
        parser.add_argument('--department', action='append',
                            help='restrict to this INSEE prefix, e.g. 44 or 2A (repeatable)')
        parser.add_argument('--dry-run', action='store_true',
                            help='only report what would change')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        departments = options['department']
        self.info(f'Starting to update city locations{" (dry run)" if dry_run else ""}...')
        stats = update_city_locations(departments=departments, dry_run=dry_run, log=self.info)
        print_city_location_stats(self, stats, dry_run)
