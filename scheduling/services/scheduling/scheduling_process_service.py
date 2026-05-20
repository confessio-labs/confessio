from django.db import transaction

from core.utils.log_utils import info
from registry.models import Website
from scheduling.models import Scheduling, PruningParsing
from scheduling.services.scheduling.index_scheduling_service import do_index_scheduling, \
    clean_parsings_moderations
from scheduling.services.scheduling.init_scheduling_service import build_scheduling, \
    bulk_create_scheduling_related_objects
from scheduling.services.scheduling.match_scheduling_service import \
    bulk_create_scheduling_matching_objects, \
    do_match_scheduling
from scheduling.services.scheduling.parse_scheduling_service import do_parse_scheduling, \
    bulk_create_scheduling_parsing_objects
from scheduling.services.scheduling.prune_scheduling_service import do_prune_scheduling, \
    bulk_create_scheduling_pruning_objects
from scheduling.services.scheduling.scheduling_moderation_service import \
    add_necessary_scheduling_moderation
from scheduling.tasks import worker_prune_scheduling, worker_parse_scheduling


def init_scheduling(website: Website, instant_deindex: bool = False) -> Scheduling:
    info(f"Initializing scheduling for website {website}.")

    new_scheduling, scheduling_related_objects = build_scheduling(website)
    with transaction.atomic():
        # Cancel any existing in-progress Scheduling for this website
        uuids_to_cancel = list(
            Scheduling.objects.select_for_update().filter(
                website=website,
                status__in=[
                    Scheduling.Status.BUILT,
                    Scheduling.Status.PRUNED,
                    Scheduling.Status.PARSED,
                    Scheduling.Status.MATCHED,
                ],
            ).values_list('uuid', flat=True)
        )
        Scheduling.objects.filter(uuid__in=uuids_to_cancel).delete()

        if instant_deindex:
            uuids_to_deindex = list(
                Scheduling.objects.select_for_update().filter(
                    website=website,
                    status=Scheduling.Status.INDEXED,
                ).values_list('uuid', flat=True)
            )
            Scheduling.objects.filter(uuid__in=uuids_to_deindex).delete()

        # Save new Scheduling
        new_scheduling.save()

        # Bulk create related objects
        bulk_create_scheduling_related_objects(new_scheduling, scheduling_related_objects)

    # trigger prune_scheduling in background
    worker_prune_scheduling(str(new_scheduling.uuid))

    return new_scheduling


def prune_scheduling(scheduling: Scheduling):
    info("Pruning scheduling.")
    if scheduling.status != Scheduling.Status.BUILT:
        info(f"Scheduling is in status {scheduling.status}; skipping pruning.")
        return

    scheduling_pruning_objects = do_prune_scheduling(scheduling)

    with transaction.atomic():
        # 1. Verify the scheduling is still in BUILT status
        try:
            scheduling = Scheduling.objects.select_for_update().get(
                uuid=scheduling.uuid,
                status=Scheduling.Status.BUILT
            )
        except Scheduling.DoesNotExist:
            info("Aborting: Scheduling not found or status changed.")
            return

        # 2. Save pruning objects
        bulk_create_scheduling_pruning_objects(scheduling, scheduling_pruning_objects)

        # 3. Mark scheduling as PRUNED
        scheduling.status = Scheduling.Status.PRUNED
        scheduling.save()

    # trigger parse_scheduling in background
    worker_parse_scheduling(str(scheduling.uuid))


def parse_scheduling(scheduling: Scheduling):
    info("Parsing scheduling.")
    if scheduling.status != Scheduling.Status.PRUNED:
        info(f"Scheduling is in status {scheduling.status}; skipping parsing.")
        return

    scheduling_parsing_objects = do_parse_scheduling(scheduling)

    with transaction.atomic():
        # 1. Verify the scheduling is still in PRUNED status
        try:
            scheduling = Scheduling.objects.select_for_update().get(
                uuid=scheduling.uuid,
                status=Scheduling.Status.PRUNED
            )
        except Scheduling.DoesNotExist:
            info("Aborting: Scheduling not found or status changed.")
            return

        # 2. Save pruning objects
        bulk_create_scheduling_parsing_objects(scheduling, scheduling_parsing_objects)

        # 3. Mark scheduling as PARSED
        scheduling.status = Scheduling.Status.PARSED
        scheduling.save()

    # trigger match_scheduling synchronously
    match_scheduling(scheduling)


def match_scheduling(scheduling: Scheduling):
    info("Match scheduling.")
    if scheduling.status != Scheduling.Status.PARSED:
        info(f"Scheduling is in status {scheduling.status}; skipping parsing.")
        return

    scheduling_matching_objects = do_match_scheduling(scheduling)

    with transaction.atomic():
        # 1. Verify the scheduling is still in PARSED status
        try:
            scheduling = Scheduling.objects.select_for_update().get(
                uuid=scheduling.uuid,
                status=Scheduling.Status.PARSED
            )
        except Scheduling.DoesNotExist:
            info("Aborting: Scheduling not found or status changed.")
            return

        # 2. Save pruning objects
        bulk_create_scheduling_matching_objects(scheduling, scheduling_matching_objects)

        # 3. Mark scheduling as MATCHED
        scheduling.status = Scheduling.Status.MATCHED
        scheduling.save()

    # trigger index_scheduling synchronously
    index_scheduling(scheduling)


def index_scheduling(scheduling: Scheduling):
    info("Indexing scheduling.")

    if scheduling.status != Scheduling.Status.MATCHED:
        info(f"Scheduling is in status {scheduling.status}; skipping indexing.")
        return

    indexing_objects = do_index_scheduling(scheduling)

    with transaction.atomic():
        # 1. Verify the scheduling is still in MATCHED status
        try:
            scheduling = Scheduling.objects.select_for_update().get(
                uuid=scheduling.uuid,
                status=Scheduling.Status.MATCHED
            )
        except Scheduling.DoesNotExist:
            info("Aborting: Scheduling not found or status changed.")
            return

        # 2. Delete previous INDEXED schedulings for the same website
        # This will cascade delete related indexed events
        indexed_schedulings = Scheduling.objects.filter(website=scheduling.website,
                                                        status=Scheduling.Status.INDEXED)
        if indexing_objects.resources_hash in \
                indexed_schedulings.values_list('resources_hash', flat=True).distinct():
            info("Aborting: An identical scheduling has already been indexed.")
            scheduling.delete()
            return

        # we save parsing_history_ids to later clean up moderations
        parsing_history_ids = PruningParsing.objects.filter(scheduling__in=indexed_schedulings)\
            .values_list('parsing_history_id', flat=True).distinct()
        indexed_schedulings.delete()

        # 3. Save index events
        for index_event in indexing_objects.index_events:
            index_event.save()

        # 4. Mark scheduling as INDEXED
        scheduling.status = Scheduling.Status.INDEXED
        scheduling.sourced_schedules_list = \
            indexing_objects.sourced_schedules_list.model_dump(mode='json')
        scheduling.church_uuid_by_id = indexing_objects.church_uuid_by_id
        scheduling.resources_hash = indexing_objects.resources_hash
        scheduling.save()

    add_necessary_scheduling_moderation(scheduling, indexing_objects)
    clean_parsings_moderations(list(parsing_history_ids))
