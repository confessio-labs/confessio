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
    try:
        moderation = OClocherOrganizationModeration.objects.get(website=website, category=category)
        if moderation.oclocher_organization != oclocher_organization:
            moderation.oclocher_organization = oclocher_organization
            moderation.save()
    except OClocherOrganizationModeration.DoesNotExist:
        moderation = OClocherOrganizationModeration(
            website=website, category=category,
            diocese=website.get_diocese(),
            oclocher_organization=oclocher_organization,
            status=ModerationStatus.TO_VALIDATE,
        )
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
    try:
        moderation = OClocherMatchingModeration.objects.get(
            oclocher_organization=oclocher_organization)
        if moderation.oclocher_matching != oclocher_matching or moderation.category != category:
            moderation.oclocher_matching = oclocher_matching
            moderation.category = category
            moderation.status = (ModerationStatus.VALIDATED
                                 if moderation_validated
                                 else ModerationStatus.TO_VALIDATE)
            moderation.save()
            notify_if_relevant(moderation)
    except OClocherMatchingModeration.DoesNotExist:
        moderation = OClocherMatchingModeration(
            oclocher_matching=oclocher_matching, category=category,
            oclocher_organization=oclocher_organization,
            diocese=oclocher_organization.website.get_diocese(),
            status=(ModerationStatus.VALIDATED
                    if moderation_validated
                    else ModerationStatus.TO_VALIDATE),
        )
        moderation.save()
        notify_if_relevant(moderation)
