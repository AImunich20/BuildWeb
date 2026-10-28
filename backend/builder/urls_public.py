from django.urls import path, re_path

from . import public

urlpatterns = [
    path("", public.public),
    re_path(r"^(?P<path>.+)$", public.public),
]
