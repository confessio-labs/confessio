from django.contrib import admin
from django.forms import ModelChoiceField
from leaflet.admin import LeafletGeoAdmin, LeafletGeoAdminMixin
from simple_history.admin import SimpleHistoryAdmin

from crawling.models import WebsiteForbiddenPath
from registry.models import Church, City, Parish, Diocese, Website


@admin.register(Diocese)
class DioceseAdmin(SimpleHistoryAdmin):
    list_display = ["name", "slug", "messesinfo_network_id"]


class ParishInline(admin.StackedInline):
    model = Parish
    show_change_link = True


class WebsiteForbiddenPathInline(admin.StackedInline):
    model = WebsiteForbiddenPath


@admin.register(Website)
class WebsiteAdmin(SimpleHistoryAdmin):
    list_display = ["name"]
    search_fields = ["name"]
    inlines = [
        ParishInline,
        WebsiteForbiddenPathInline,
    ]


class ChurchInline(LeafletGeoAdminMixin, admin.StackedInline):
    model = Church
    show_change_link = True


@admin.register(Parish)
class ParishAdmin(SimpleHistoryAdmin):
    list_display = ["name", "website"]
    search_fields = ["name"]
    autocomplete_fields = ["website"]
    inlines = [
        ChurchInline,
    ]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'diocese':
            return DioceseChoiceField(queryset=Diocese.objects.all())
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Church)
class ChurchAdmin(LeafletGeoAdmin, SimpleHistoryAdmin):
    list_display = ["name"]
    search_fields = ["name"]
    autocomplete_fields = ["parish"]
    display_raw = True

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(City)
class CityAdmin(LeafletGeoAdmin):
    list_display = ["name", "zipcode", "population"]
    search_fields = ["name", "zipcode"]
    display_raw = True


# https://books.agiliq.com/projects/django-admin-cookbook/en/latest/fk_display.html
class WebsiteChoiceField(ModelChoiceField):
    def label_from_instance(self, obj):
        return "Website: {}".format(obj.name)


class ParishChoiceField(ModelChoiceField):
    def label_from_instance(self, obj):
        return "Parish: {}".format(obj.name)


class DioceseChoiceField(ModelChoiceField):
    def label_from_instance(self, obj):
        return "Diocese: {}".format(obj.name)
