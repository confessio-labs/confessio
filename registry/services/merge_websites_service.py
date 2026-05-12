from registry.models import Website, WebsiteModeration, Diocese
from registry.models.base_moderation_models import ModerationStatus
from registry.services.website_name_service import clean_website_name
from registry.utils.extract_title import get_page_title


def add_website_moderation(website: Website, category: WebsiteModeration.Category,
                           diocese: Diocese = None):
    try:
        # we need to delete existing moderation first
        existing_category = WebsiteModeration.objects.get(website=website, category=category)
        existing_category.delete()
    except WebsiteModeration.DoesNotExist:
        pass

    website_moderation = WebsiteModeration(
        website=website,
        category=category,
        diocese=diocese or website.get_diocese(),
        status=ModerationStatus.TO_VALIDATE,
    )
    website_moderation.save()


def update_website_name(website: Website, other_website_name: str):
    page_title = get_page_title(website.home_url)

    if page_title:
        # If home_url's title exists we replace website name by it
        website.name = page_title
        moderation_category = WebsiteModeration.Category.NAME_WEBSITE_TITLE
    else:
        # If there is a problem with home_url, new name is concatenation of both website names
        all_names = website.name + other_website_name
        concatenated_name = ' - '.join(all_names)
        print(f'got new name {concatenated_name}')

        website.name = concatenated_name
        moderation_category = WebsiteModeration.Category.NAME_CONCATENATED

    # We update website
    website.save()
    clean_website_name(website)

    # We will need to moderate generated website name
    add_website_moderation(website, moderation_category)


def merge_websites(website: Website, primary_website: Website):
    # We update primary_website name (website title or concatenated names)
    update_website_name(primary_website, website.name)

    # We assign other parishes to website
    for parish in website.parishes.all():
        parish.website = primary_website
        parish.save()

    # Finally we delete other website
    website.delete()
