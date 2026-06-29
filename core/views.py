from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest, HttpResponseNotFound, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from registry.models import ModerationMixin, Diocese
from registry.models.base_moderation_models import ModerationStatus
from scheduling.utils.date_utils import datetime_to_ts_us, ts_us_to_datetime


def get_moderation_url(moderation: ModerationMixin):
    return reverse(f'moderate_one_' + moderation.resource,
                   kwargs={
                       'category': moderation.category,
                       'status': moderation.status,
                       'moderation_uuid': moderation.uuid,
                       'diocese_slug': moderation.get_diocese_slug(),
                   })


def redirect_to_moderation(moderation: ModerationMixin, category: str, resource: str,
                           status: str, diocese_slug: str):
    if moderation is None:
        return redirect('moderation_home')
    else:
        return redirect(f'moderate_one_' + resource,
                        category=category,
                        status=status,
                        moderation_uuid=moderation.uuid,
                        diocese_slug=diocese_slug)


class ModerationPostError(Exception):
    response: HttpResponse

    def __init__(self, response: HttpResponse):
        self.response = response


def get_next_url(request, moderation: ModerationMixin, diocese_slug: str) -> str:
    created_at_ts_us = datetime_to_ts_us(moderation.created_at)
    back_path = request.GET.get('backPath', '')
    if back_path:
        return back_path

    next_url = \
        reverse('moderate_next_' + moderation.resource,
                kwargs={
                    'category': moderation.category,
                    'status': moderation.status,
                    'diocese_slug': diocese_slug,
                }) \
        + f'?created_after={created_at_ts_us}'

    related_url = request.POST.get('related_url')
    if related_url:
        return f"{related_url}?backPath={next_url}"

    return next_url


def get_position_and_count(moderation: ModerationMixin,
                           diocese: Diocese | None,
                           status: str,
                           ) -> tuple[int, int]:
    objects_filter = moderation.__class__.objects.filter(
        category=moderation.category,
        status=status,
    )
    if diocese:
        objects_filter = objects_filter.filter(diocese=diocese)
    counts = objects_filter.aggregate(
        position=Count("uuid", filter=Q(created_at__lte=moderation.created_at)),
        total=Count("uuid"),
    )
    return counts["position"], counts["total"]


@dataclass
class HistoryEntry:
    date: datetime
    user: User | None
    is_creation: bool = False
    old_status: ModerationStatus | None = None
    new_status: ModerationStatus | None = None
    old_category: str | None = None
    new_category: str | None = None
    comment: str | None = None


def get_moderation_history(
    moderation: ModerationMixin,
) -> list[HistoryEntry]:
    records = list(
        moderation.history.all()
        .select_related('history_user')
        .order_by('-history_date')[:21]
    )
    entries: list[HistoryEntry] = []
    for i, record in enumerate(records):
        if record.history_type == '+':
            entries.append(HistoryEntry(
                date=record.history_date,
                user=record.history_user,
                is_creation=True,
                new_status=ModerationStatus(record.status),
                new_category=record.category,
            ))
        elif i + 1 < len(records):
            prev = records[i + 1]
            entry = HistoryEntry(
                date=record.history_date,
                user=record.history_user,
            )
            has_change = False
            if record.status != prev.status:
                entry.old_status = ModerationStatus(prev.status)
                entry.new_status = ModerationStatus(record.status)
                has_change = True
            if record.category != prev.category:
                entry.old_category = prev.category
                entry.new_category = record.category
                has_change = True
            if record.comment != prev.comment and record.comment:
                entry.comment = record.comment
                has_change = True
            if has_change:
                entries.append(entry)
    return entries


def get_moderate_response(request, category: str, resource: str, status: str,
                          diocese_slug: str, class_moderation, moderation_uuid, create_context,
                          moderation_post_process=None):
    if status not in ModerationStatus.values:
        return HttpResponseBadRequest(f"status {status} is not valid")

    if category not in class_moderation.Category.values:
        return HttpResponseBadRequest(f"category {category} is not valid for {resource}")

    if diocese_slug == 'no_diocese':
        diocese = None
    else:
        try:
            diocese = Diocese.objects.get(slug=diocese_slug)
        except Diocese.DoesNotExist:
            return HttpResponseNotFound(f"diocese {diocese_slug} not found")

    if moderation_uuid is None:
        created_after_ts = int(request.GET.get('created_after', '0'))
        created_after = ts_us_to_datetime(created_after_ts)
        objects_filter = class_moderation.objects.filter(
            category=category,
            status=status,
            created_at__gt=created_after,
        )
        if diocese:
            objects_filter = objects_filter.filter(diocese=diocese)
        next_moderation = objects_filter.order_by('created_at').first()
        return redirect_to_moderation(next_moderation, category, resource, status, diocese_slug)

    try:
        moderation = class_moderation.objects.get(uuid=moderation_uuid)
    except class_moderation.DoesNotExist:
        print(f"{resource} {moderation_uuid} not found. "
              f"Probably because problem was solved meanwhile. "
              f"Redirecting to first moderation.")
        return redirect('moderate_next_' + resource, category=category, status=status,
                        diocese_slug=diocese_slug)

    do_redirect = True
    next_url = get_next_url(request, moderation, diocese_slug)
    if request.method == "POST":
        if 'change_status' in request.POST:
            new_status = request.POST.get('change_status')
            if new_status not in ModerationStatus.values:
                return HttpResponseBadRequest(
                    f"status {new_status} is not valid")
            comment = request.POST.get('comment') or None
            moderation.comment = comment
            if new_status != moderation.status:
                moderation.set_status(new_status, request.user)
            else:
                moderation.save()
            do_redirect = False
        elif 'delete_moderation' in request.POST:
            moderation.delete()
        elif moderation_post_process is not None:
            try:
                do_redirect = moderation_post_process(request, moderation)
            except ModerationPostError as e:
                return e.response

            if do_redirect:
                moderation.validate(request.user)

        if do_redirect:
            return redirect(next_url)

    position, count = get_position_and_count(moderation, diocese, status)
    history_entries = get_moderation_history(moderation)

    return render(request, f'moderations/moderate_{moderation.resource}.html', {
        'moderation': moderation,
        'next_url': next_url,
        'back_path': request.GET.get('backPath', ''),
        'position': position,
        'count': count,
        'moderation_statuses': ModerationStatus,
        'history_entries': history_entries,
    } | create_context(moderation))
