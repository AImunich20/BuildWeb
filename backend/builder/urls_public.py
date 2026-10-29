from django.conf import settings
from django.urls import path, re_path

from . import public

urlpatterns = []
if settings.SERVER_MODE:
    from django.contrib import admin
    from django.contrib.staticfiles.views import serve as static_serve

    from . import server_api

    urlpatterns += [
        path("__bw/health", server_api.health),
        path("__bw/deploy", server_api.deploy),
        path("__bw/pull", server_api.pull),
        path("__bw/config", server_api.server_config),
        path("__bw/domain-check", server_api.domain_check),
        path("__bw/admin/", admin.site.urls),
        re_path(r"^__bw/static/(?P<path>.*)$", static_serve, {"insecure": True}),
    ]

urlpatterns += [
    path("", public.public),
    re_path(r"^(?P<path>.+)$", public.public),
]
