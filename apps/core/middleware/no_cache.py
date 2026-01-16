class NoCacheAppMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path or ""
        if not path.startswith("/app/"):
            return response
        if path.startswith(("/app/static/", "/app/media/")):
            return response
        if path.startswith("/app/api/"):
            return response
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        response["Vary"] = "Cookie"
        return response
