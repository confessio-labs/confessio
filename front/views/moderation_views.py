from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render

from core.views import get_moderate_response
from front.models import ReportModeration
from front.services.moderation_stats_service import get_moderation_stats_by_diocese


@login_required
@permission_required("scheduling.change_sentence")
def moderation_home(request):
    return render(request, 'pages/moderation_home.html', {
        'dioceses_with_stats': get_moderation_stats_by_diocese(),
    })


@login_required
@permission_required("scheduling.change_sentence")
def moderate_report(request, category, status, diocese_slug, moderation_uuid=None):
    return get_moderate_response(request, category, 'report', status, diocese_slug,
                                 ReportModeration, moderation_uuid,
                                 create_report_moderation_context)


def create_report_moderation_context(moderation: ReportModeration) -> dict:
    report = moderation.report
    assert report is not None

    return {
        'report': report,
    }
