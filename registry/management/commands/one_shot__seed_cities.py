from core.management.abstract_command import AbstractCommand
from registry.services.city_service import build_city, refresh_city_slugs, upsert_cities
from registry.utils.gouv_fr_utils import fetch_communes


class Command(AbstractCommand):
    help = "One shot command to seed French cities from geo.api.gouv.fr."

    def handle(self, *args, **options):
        self.info('Starting one shot command to seed cities...')
        communes = fetch_communes()
        if not communes:
            self.error('Got no commune from geo.api.gouv.fr, aborting.')
            return

        self.info(f'Fetched {len(communes)} communes, building cities...')
        cities = []
        nb_skipped = 0
        for commune in communes:
            city = build_city(commune)
            if city is None:
                nb_skipped += 1
                continue
            cities.append(city)

        upsert_cities(cities)
        self.success(f'Successfully seeded {len(cities)} cities ({nb_skipped} skipped).')

        self.info('Refreshing city slugs...')
        nb_cities, nb_changed = refresh_city_slugs()
        self.success(f'Successfully computed {nb_cities} city slugs, {nb_changed} updated.')
