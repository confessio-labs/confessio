from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponseNotFound
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from core.views import get_moderate_response
from crawling.models import CrawlingModeration
from crawling.tasks import worker_crawl_website
from registry.models import Website


@login_required
@permission_required("scheduling.change_sentence")
def moderate_crawling(request, category, status, diocese_slug, moderation_uuid=None):
    return get_moderate_response(request, category, 'crawling', status, diocese_slug,
                                 CrawlingModeration, moderation_uuid,
                                 create_crawling_moderation_context)


def create_crawling_moderation_context(moderation: CrawlingModeration) -> dict:
    return {
        'website': moderation.website,
    }


@login_required
@permission_required("scheduling.change_sentence")
@require_POST
def trigger_recrawl_for_website(request, website_uuid=None):
    try:
        website = Website.objects.get(uuid=website_uuid)
    except Website.DoesNotExist:
        return HttpResponseNotFound(f'website not found with uuid {website_uuid}')

    worker_crawl_website(str(website.uuid), None)

    next_url = request.POST.get('next', '/')
    return redirect(next_url)
