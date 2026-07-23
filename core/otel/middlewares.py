import time
from django.db import connection


class TelemetryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        from core.otel.metrics_service import metrics_service
        self.metrics_service = metrics_service

    def __call__(self, request):
        start_time = time.perf_counter()
        db_time = 0.0

        # Define the DB wrapper
        def profile_queries(execute, sql, params, many, context):
            nonlocal db_time
            start = time.perf_counter()
            try:
                return execute(sql, params, many, context)
            finally:
                db_time += (time.perf_counter() - start)

        # 1. Wrap the entire inner request/response cycle
        with connection.execute_wrapper(profile_queries):
            response = self.get_response(request)

        # 2. After the response is generated, calculate and export
        if request.resolver_match:
            total_duration = time.perf_counter() - start_time
            url_name = self._get_cleaned_url_name(request)

            # Export to OTEL
            self.metrics_service.record_response_time(total_duration, db_time, url_name)

        return response

    @staticmethod
    def _get_cleaned_url_name(request):
        url_name = request.resolver_match.url_name or "unknown"

        # regrouping url_name for better metrics aggregation
        if url_name in ['index', 'around_place_view', 'city_view', 'in_area_view',
                        'around_me_view']:
            return 'legacy_search'
        if url_name == 'autocomplete':
            return 'legacy_autocomplete'
        if url_name.startswith('api_front'):
            return url_name
        if url_name.startswith('api_public'):
            return 'api_public'

        whitelist = ['diocese_view', 'website_view']

        return url_name if url_name in whitelist else 'other'
