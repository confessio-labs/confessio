from core.management.abstract_cleaning_command import AbstractCleaningCommand
from registry.models import ChurchModeration, Website, WebsiteModeration, Parish
from registry.models.base_moderation_models import ModerationStatus


class Command(AbstractCleaningCommand):
    help = "Clean registry-related data from the database"

    def handle(self, *args, **options):
        # Delete parishes without churches
        self.info('Starting cleaning parishes without church')
        parish_count, _ = Parish.objects.filter(churches__isnull=True).delete()
        self.success(f"Deleted {parish_count} parishes without churches.")

        # Delete websites without parishes
        self.info('Starting cleaning websites without parish')
        website_count, _ = Website.objects.filter(parishes__isnull=True).delete()
        self.success(f"Deleted {website_count} websites without parishes.")

        # Church moderation
        self.info('Starting cleaning church moderation items')
        counter = 0
        for church_moderation in ChurchModeration.objects.filter(
            category=ChurchModeration.Category.LOCATION_DIFFERS,
        ).exclude(status=ModerationStatus.VALIDATED).all():
            if not church_moderation.location_desc_differs():
                church_moderation.delete()
                counter += 1
        self.success(f'Done removing {counter} church moderation items')

        # Website history
        self.delete_irrelevant_history(Website, {
            'updated_at', 'nb_recent_hits', 'is_best_diocese_hit'})

        # Website moderation history
        self.delete_irrelevant_history(WebsiteModeration, {'updated_at'})
