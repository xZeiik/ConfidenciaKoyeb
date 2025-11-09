# core/middleware.py
from django.http import HttpResponse
def host_echo(get_response):
    def middleware(request):
        # descomenta para ver host en logs
         print("HOST:", request.get_host())
        return get_response(request)
    return middleware
