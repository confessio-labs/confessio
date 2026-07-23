from request.middleware import RequestMiddleware


class FullPathRequestMiddleware(RequestMiddleware):
    """django-request only logs request.path, dropping the query string.

    We temporarily swap in get_full_path() so that the stored Request.path keeps the query
    params (truncated to 255 chars by Request.from_http_request).
    """

    def process_response(self, request, response):
        original_path = request.path
        request.path = request.get_full_path()
        try:
            return super().process_response(request, response)
        finally:
            request.path = original_path
