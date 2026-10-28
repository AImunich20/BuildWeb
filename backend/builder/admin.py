from django.contrib import admin

from .models import Asset, AssetFolder, Collection, DataConnection, FormSubmission, Page, PageRevision, Record, SharedSection, Site


class PageInline(admin.TabularInline):
    model = Page
    fields = ("title", "slug", "is_home", "status", "show_in_nav", "nav_order")
    extra = 0
    show_change_link = True


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "published", "updated_at")
    list_filter = ("published",)
    search_fields = ("name", "slug", "description")
    inlines = [PageInline]


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "site", "slug", "is_home", "status", "show_in_nav", "nav_order", "updated_at")
    list_filter = ("site", "status", "show_in_nav")
    search_fields = ("title", "slug", "seo_title", "seo_description")
    list_editable = ("status", "show_in_nav", "nav_order")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("site", "title", "slug", "is_home", "status", "parent")}),
        ("เมนู", {"fields": ("show_in_nav", "nav_label", "nav_order")}),
        ("SEO", {"fields": ("seo_title", "seo_description", "seo_keywords", "og_image", "noindex")}),
        ("โค้ดเพิ่มเติม", {"classes": ("collapse",), "fields": ("head_code", "custom_css", "custom_js")}),
        ("เนื้อหา (แก้ใน Editor)", {"classes": ("collapse",), "fields": ("html", "css", "created_at", "updated_at")}),
    )


@admin.register(PageRevision)
class PageRevisionAdmin(admin.ModelAdmin):
    list_display = ("page", "note", "created_at")
    list_filter = ("page__site",)


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("name", "site", "folder", "kind", "size", "created_at")
    list_filter = ("site", "kind")
    search_fields = ("name", "alt")


admin.site.register(AssetFolder)


@admin.register(FormSubmission)
class FormSubmissionAdmin(admin.ModelAdmin):
    list_display = ("site", "form_name", "page", "is_read", "created_at")
    list_filter = ("site", "is_read", "form_name")
    readonly_fields = ("site", "page", "form_name", "data", "ip", "user_agent", "created_at")


admin.site.register(SharedSection)


class RecordInline(admin.TabularInline):
    model = Record
    extra = 0
    fields = ("position", "data")


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("name", "site", "slug", "mode", "source_table", "updated_at")
    list_filter = ("site", "mode")
    inlines = [RecordInline]


@admin.register(DataConnection)
class DataConnectionAdmin(admin.ModelAdmin):
    list_display = ("name", "host", "port", "user", "database")
    exclude = ("password",)
