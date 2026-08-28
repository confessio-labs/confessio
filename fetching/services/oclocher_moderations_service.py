from django.conf import settings
from core.utils.discord_utils import send_discord_alert, DiscordChanel
from core.views import get_moderation_url
from fetching.models import OClocherOrganization, OClocherMatchingModeration, OClocherMatching
from fetching.models.oclocher_moderation_models import OClocherOrganizationModeration
from registry.models import Website
from registry.models.base_moderation_models import ModerationStatus


def add_organization_moderation(website: Website,
                                category: OClocherOrganizationModeration.Category,
                                oclocher_organization: OClocherOrganization | None = None,
                                ):
    # get_or_create so that two concurrent fetchings of the same website don't both insert
    moderation, created = OClocherOrganizationModeration.objects.get_or_create(
        website=website, category=category,
        defaults={
            'diocese': website.get_diocese(),
            'oclocher_organization': oclocher_organization,
            'status': ModerationStatus.TO_VALIDATE,
        },
    )
    if not created and moderation.oclocher_organization != oclocher_organization:
        moderation.oclocher_organization = oclocher_organization
        moderation.save()


def notify_if_relevant(moderation: OClocherMatchingModeration,):
    if moderation.category == OClocherMatchingModeration.Category.OK:
        return

    moderation_url = settings.REQUEST_BASE_URL + get_moderation_url(moderation)
    send_discord_alert(f"OClocher matching issue ({moderation.category}) "
                       f"on website {moderation.oclocher_organization.website.name} "
                       f"{moderation_url}",
                       DiscordChanel.PB_OCLOCHER)


def upsert_matching_moderation(oclocher_organization: OClocherOrganization,
                               oclocher_matching: OClocherMatching,
                               category: OClocherMatchingModeration.Category,
                               moderation_validated: bool):
    status = (ModerationStatus.VALIDATED
              if moderation_validated
              else ModerationStatus.TO_VALIDATE)
    # get_or_create so that two concurrent matchings of the same organization don't both insert
    moderation, created = OClocherMatchingModeration.objects.get_or_create(
        oclocher_organization=oclocher_organization,
        defaults={
            'oclocher_matching': oclocher_matching,
            'category': category,
            'diocese': oclocher_organization.website.get_diocese(),
            'status': status,
        },
    )
    if created:
        notify_if_relevant(moderation)
    elif moderation.oclocher_matching != oclocher_matching or moderation.category != category:
        moderation.oclocher_matching = oclocher_matching
        moderation.category = category
        moderation.status = status
        moderation.save()
        notify_if_relevant(moderation)
