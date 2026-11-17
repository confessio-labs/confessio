from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render

from front.services.stats_service import get_stats_charts
from front.utils.stats_utils import parse_period


@login_required
@permission_required("scheduling.change_sentence")
def stats(request):
    period = parse_period(request.GET.get('period'))
    return render(request, 'pages/stats.html', {
        'charts': get_stats_charts(period),
        'period': period,
    })
