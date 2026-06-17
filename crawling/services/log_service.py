from django.utils import timezone

from core.utils.log_utils import get_log_buffer
from crawling.models import Log
from crawling.utils.string_utils import remove_unsafe_chars
from registry.models import Website


def save_buffer(website: Website, log_type: Log.Type, status: Log.Status = Log.Status.DONE,
                error_detail: str | None = None,
                nb_visited_links: int | None = None,
                nb_success_links: int | None = None):
    buffer_value, buffer_started_at = get_log_buffer()
    log = Log(type=log_type,
              website=website,
              content=remove_unsafe_chars(buffer_value),
              status=status,
              started_at=buffer_started_at,
              end_at=timezone.now(),
              error_detail=remove_unsafe_chars(error_detail),
              nb_visited_links=nb_visited_links,
              nb_success_links=nb_success_links,
              )
    log.save()
