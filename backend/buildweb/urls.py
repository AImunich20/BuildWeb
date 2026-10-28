from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.views import serve as static_serve
from django.urls import path, re_path
from django.views.static import serve as media_serve

from builder import api, public, views

admin.site.site_header = "BuildWeb — ผู้ดูแลระบบ"
admin.site.site_title = "BuildWeb Admin"
admin.site.index_title = "จัดการข้อมูลทั้งหมด"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("sites/<int:site_id>/", views.site_manage, name="site"),
    path("sites/<int:site_id>/edit/", views.editor_home),
    path("sites/<int:site_id>/edit/<int:page_id>/", views.editor, name="editor"),
    path("sites/<int:site_id>/edit-shared/<str:kind>/", views.editor_shared, name="editor_shared"),
    path("sites/<int:site_id>/forms.csv", views.submissions_csv, name="submissions_csv"),
    path("sites/<int:site_id>/<str:tab>/", views.site_manage, name="site_tab"),
    path("settings/", views.settings_page, name="settings"),
    path("settings/database/", views.database_page, name="database"),
    path("settings/notify/", views.notify_page, name="notify"),
    path("django-admin/", admin.site.urls),
    # preview (drafts included)
    path("preview/<slug:slug>", public.preview),
    path("preview/<slug:slug>/", public.preview),
    re_path(r"^preview/(?P<slug>[\w-]+)/(?P<path>.+)$", public.preview),
    # API
    path("api/sites/create", api.site_create),
    path("api/sites/<int:site_id>/update", api.site_update),
    path("api/sites/<int:site_id>/delete", api.site_delete),
    path("api/sites/<int:site_id>/duplicate", api.site_duplicate),
    path("api/sites/<int:site_id>/pages", api.page_list),
    path("api/sites/<int:site_id>/pages/create", api.page_create),
    path("api/sites/<int:site_id>/pages/reorder", api.page_reorder),
    path("api/sites/<int:site_id>/pages/sync-nav", api.page_nav_sync),
    path("api/sites/<int:site_id>/assets", api.asset_list),
    path("api/sites/<int:site_id>/assets/upload", api.asset_upload),
    path("api/sites/<int:site_id>/folders/create", api.folder_create),
    path("api/sites/<int:site_id>/folders/delete", api.folder_delete),
    path("api/sites/<int:site_id>/submissions", api.submission_list),
    path("api/sites/<int:site_id>/submissions/read-all", api.submission_read_all),
    path("api/sites/<int:site_id>/export", api.site_export),
    path("api/sites/<int:site_id>/shared/extract", api.shared_extract),
    path("api/shared/<int:shared_id>/project", api.shared_project),
    path("api/shared/<int:shared_id>/update", api.shared_update),
    path("api/pages/<int:page_id>/update", api.page_update),
    path("api/pages/<int:page_id>/delete", api.page_delete),
    path("api/pages/<int:page_id>/duplicate", api.page_duplicate),
    path("api/pages/<int:page_id>/home", api.page_make_home),
    path("api/pages/<int:page_id>/project", api.page_project),
    path("api/pages/<int:page_id>/revisions", api.revision_list),
    path("api/pages/<int:page_id>/snapshot", api.revision_snapshot),
    path("api/revisions/<int:rev_id>/restore", api.revision_restore),
    path("api/assets/<int:asset_id>/update", api.asset_update),
    path("api/assets/<int:asset_id>/delete", api.asset_delete),
    path("api/submissions/<int:sub_id>/<str:action>", api.submission_action),
    path("api/editor/sections", api.editor_sections),
    path("api/import/upload", api.import_upload),
    path("api/import/github", api.import_github),
    path("api/system/reveal", api.reveal),
    path("api/system/open-url", api.open_url),
    path("api/system/restart", api.system_restart),
    path("api/settings/hosting", api.hosting_settings),
    path("api/settings/notify", api.notify_settings),
    path("api/settings/notify/test", api.notify_test),
    path("api/settings/app", api.app_settings),
    path("api/settings/db/status", api.db_status),
    path("api/settings/db/test", api.db_test),
    path("api/settings/db/switch", api.db_switch),
    # files
    re_path(r"^static/(?P<path>.*)$", static_serve, {"insecure": True}),
    re_path(r"^media/(?P<path>.*)$", media_serve, {"document_root": settings.MEDIA_ROOT}),
]
