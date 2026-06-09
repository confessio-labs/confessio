import time

from django.db.models import Max

from core.management.abstract_command import AbstractCommand
from core.utils.heartbeat_utils import ping_heartbeat
from registry.models import Church
from registry.services.sync_annuairecatholique_service import \
    sync_annuairecatholique_for_church, sync_annuairecatholique_location_and_city, \
    link_church_to_place
from registry.utils.annuairecatholique_utils import fetch_places


class Command(AbstractCommand):
    help = "Sync with annuairecatholique API"

    def add_arguments(self, parser):
        parser.add_argument('-d', '--diocese', help='diocese messesinfo_network_id to sync')
        parser.add_argument('-a', '--all', help='sync all churches', action='store_true')
        parser.add_argument('-t', '--timeout', help='timeout in seconds', type=int, default=0)

    def handle(self, *args, **options):
        if not options['all'] and not options['diocese']:
            self.handle_from_last_updated_at(timeout=options['timeout'])
            ping_heartbeat("HEARTBEAT_ANNUAIRE_URL")
            return

        if options['diocese']:
            churches = Church.objects.filter(
                parish__diocese__messesinfo_network_id=options['diocese'])
        else:
            churches = Church.objects.all()

        self.handle_for_churches(churches, timeout=options['timeout'])

    def handle_for_churches(self, churches, timeout: int = 0):
        self.info(f'Starting syncing with annuairecatholique API for specific churches')
        nb_churches = 0
        nb_no_result = 0
        nb_location_differs = 0
        nb_location_moderation = 0

        start_time = time.time()

        for church in churches:
            if timeout and time.time() - start_time > timeout:
                self.warning(f'Timeout reached, stopping the command')
                break

            self.info(f'Processing church: {church.name} ({church.uuid})')
            nb_churches += 1
            location_moderation_added = sync_annuairecatholique_for_church(church)

            if location_moderation_added is None:
                nb_no_result += 1
            else:
                nb_location_differs += 1
                if location_moderation_added:
                    nb_location_moderation += 1

        self.success(f'Sync completed: {nb_churches} churches processed, '
                     f'{nb_no_result} with no result, '
                     f'{nb_location_differs} with location differs, '
                     f'{nb_location_moderation} location moderations added.')

    def handle_from_last_updated_at(self, timeout: int = 0):
        max_updated_at = Church.objects\
            .aggregate(Max('annuairecatholique_updated_at'))['annuairecatholique_updated_at__max']
        self.info(f'Starting syncing with annuairecatholique API from last updated at: '
                  f'{max_updated_at}')

        start_time = time.time()

        page = 1
        should_stop = False
        while not should_stop:
            if timeout and time.time() - start_time > timeout:
                self.warning(f'Timeout reached, stopping the command')
                break

            places, total_pages = fetch_places(page=page)
            if not places:
                break

            self.info(f'Processing page {page}/{total_pages} with {len(places)} places...')
            for place in places:
                # high-water mark: places come ordered by updated_at desc
                if max_updated_at is not None and place.updated_at <= max_updated_at:
                    self.info(f'Reached high-water mark ({max_updated_at}), stopping.')
                    should_stop = True
                    break

                church = self.find_linkable_church(place)
                if church is None:
                    continue

                link_church_to_place(church, place)
                sync_annuairecatholique_location_and_city(church, place)

            if page >= total_pages:
                break
            page += 1

        self.success(f'Successfully synced churches from annuairecatholique.')

    @staticmethod
    def find_linkable_church(place) -> Church | None:
        try:
            return Church.objects.get(annuairecatholique_id=place.id)
        except Church.DoesNotExist:
            pass

        for messes_info in place.messes_info:
            try:
                return Church.objects.get(messesinfo_id=messes_info.id)
            except Church.DoesNotExist:
                continue

        if place.wikidata_id:
            try:
                return Church.objects.get(wikidata_id=place.wikidata_id)
            except Church.DoesNotExist:
                pass

        return None
