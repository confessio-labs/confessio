from django.contrib.gis.db import models as gis_models
from django.db import models
from simple_history.models import HistoricalRecords

from registry.models.base_moderation_models import ModerationMixin, ResourceDoesNotExistError
from registry.models import Parish, Church
from registry.services.church_name_service import sort_by_name_similarity


class WebsiteModeration(ModerationMixin):
    class Category(models.TextChoices):
        NAME_CONCATENATED = "name_concat"
        NAME_WEBSITE_TITLE = "name_websit"
        HOME_URL_CONFLICT = "hu_conflict"
        HOME_URL_TOO_LONG = "hu_too_long"
        HOME_URL_DIOCESE = "hu_diocese"
        GOOGLE_SEARCH = "google_search"

    resource = 'website'
    diocese = models.ForeignKey('Diocese', on_delete=models.CASCADE,
                                related_name=f'{resource}_moderations')
    history = HistoricalRecords()
    website = models.ForeignKey('Website', on_delete=models.CASCADE, related_name='moderations')
    category = models.CharField(max_length=32, choices=Category)

    home_url = models.URLField(null=True, max_length=255)
    other_website = models.ForeignKey('Website', on_delete=models.SET_NULL,
                                      related_name='other_moderations', null=True)

    class Meta:
        unique_together = ('website', 'category')

    def delete_on_validate(self) -> bool:
        # If other_website has been merged, we can delete this moderation
        if self.category == self.Category.HOME_URL_CONFLICT\
                and self.other_website is None:
            return True

        if self.category in [self.Category.NAME_CONCATENATED, self.Category.NAME_WEBSITE_TITLE]:
            # There is no reasons to keep those
            return True

        # in other cases we keep this moderation
        return False

    def replace_home_url(self):
        self.website.home_url = self.home_url
        self.website.save()


class ExternalSource(models.TextChoices):
    MANUAL = "manual"
    MESSESINFO = "messesinfo"
    LEHAVRE = "lehavre"
    TROUVERUNEMESSE = "trouverunemesse"
    ANNUAIRECATHOLIQUE = "annuairecatholique"


class ParishModeration(ModerationMixin):
    class Category(models.TextChoices):
        NAME_DIFFERS = "name_differs"
        WEBSITE_DIFFERS = "website_differs"
        ADDED_PARISH = "added_parish"
        DELETED_PARISH = "deleted_parish"

    resource = 'parish'
    diocese = models.ForeignKey('Diocese', on_delete=models.CASCADE,
                                related_name=f'{resource}_moderations')
    history = HistoricalRecords()
    parish = models.ForeignKey('Parish', on_delete=models.CASCADE, related_name='moderations')
    category = models.CharField(max_length=16, choices=Category)
    source = models.CharField(max_length=20, choices=ExternalSource)

    name = models.CharField(max_length=100, null=True)
    website = models.ForeignKey('Website', on_delete=models.CASCADE,
                                related_name='parish_moderations', null=True)
    similar_parishes = models.ManyToManyField('Parish', related_name='similar_moderations')

    class Meta:
        unique_together = ('parish', 'category', 'source')

    def delete_on_validate(self) -> bool:
        if self.category == self.Category.NAME_DIFFERS and self.parish.name == self.name:
            # Name has been replaced, we can delete
            return True

        if self.category == self.Category.WEBSITE_DIFFERS \
                and self.parish.website.home_url == self.website.home_url:
            # Website has been replaced, we can delete
            return True

        if self.category == self.Category.ADDED_PARISH:
            # In any case, we want to delete the moderation at validation
            return True

        # we need to keep moderations referring to external source diff
        return False

    def replace_name(self):
        self.parish.name = self.name
        self.parish.save()

    def replace_website(self):
        previous_website = self.parish.website
        self.website.is_active = True
        self.website.save()
        self.parish.website = self.website
        self.parish.save()
        previous_website.delete_if_no_parish()

    def assign_external_id(self, similar_parish_uuid):
        try:
            similar_parish = Parish.objects.get(uuid=similar_parish_uuid)
        except Parish.DoesNotExist:
            raise ResourceDoesNotExistError

        if self.source == ExternalSource.MESSESINFO:
            similar_parish.messesinfo_community_id = self.parish.messesinfo_community_id
        else:
            raise NotImplementedError

        parish_website = self.parish.website
        self.parish.delete()
        if parish_website:
            parish_website.delete_if_no_parish()
        similar_parish.save()
        # remove moderation PARISH_DELETED if exists
        ParishModeration.objects.filter(parish=similar_parish,
                                        category=self.Category.DELETED_PARISH,
                                        source=self.source).delete()


class ChurchModeration(ModerationMixin):
    class Category(models.TextChoices):
        LOCATION_NULL = "loc_null"
        LOCATION_FROM_API = "loc_api"
        NAME_DIFFERS = "name_differs"
        PARISH_DIFFERS = "parish_differs"
        LOCATION_DIFFERS = "location_differs"
        ADDED_CHURCH = "added_church"
        DELETED_CHURCH = "deleted_church"
        LOCATION_CONFLICT = "location_conflict"
        LOCATION_OUTLIER = "location_outlier"

    resource = 'church'
    diocese = models.ForeignKey('Diocese', on_delete=models.CASCADE,
                                related_name=f'{resource}_moderations')
    history = HistoricalRecords()
    church = models.ForeignKey('Church', on_delete=models.CASCADE, related_name='moderations')
    category = models.CharField(max_length=17, choices=Category)
    source = models.CharField(max_length=20, choices=ExternalSource)

    name = models.CharField(max_length=100, null=True)
    location = gis_models.PointField(geography=True, null=True)
    address = models.CharField(max_length=100, null=True)
    zipcode = models.CharField(max_length=5, null=True)
    city = models.CharField(max_length=50, null=True)
    messesinfo_id = models.CharField(max_length=100, null=True)
    parish = models.ForeignKey('Parish', on_delete=models.CASCADE,
                               related_name='church_moderations', null=True)

    similar_churches = models.ManyToManyField('Church', related_name='similar_moderations')

    class Meta:
        unique_together = ('church', 'category', 'source')

    def get_similar_churches_sorted_by_name(self) -> list[Church]:
        return sort_by_name_similarity(self.church, self.similar_churches.all())

    def delete_on_validate(self) -> bool:
        # ephemeral moderations: we can safely delete
        if self.category in [self.Category.LOCATION_NULL, self.Category.LOCATION_FROM_API]:
            return True

        if self.category == self.Category.NAME_DIFFERS and self.church.name == self.name:
            # Name has been replaced, we can delete
            return True

        if self.category == self.Category.PARISH_DIFFERS and self.church.parish == self.parish:
            # Parish has been replaced, we can delete
            return True

        if self.category == self.Category.LOCATION_DIFFERS \
                and not self.location_desc_differs():
            # Location has been replaced, we can delete
            return True

        if self.category == self.Category.ADDED_CHURCH:
            # In any case, we want to delete the moderation at validation
            return True

        # we need to keep moderations referring to external source diff
        return False

    def location_desc_differs(self):
        return (self.location is not None and self.church.location != self.location) \
            or (self.address is not None and self.church.address != self.address) \
            or (self.zipcode is not None and self.church.zipcode != self.zipcode) \
            or (self.city is not None and self.church.city != self.city)

    def replace_name(self):
        self.church.name = self.name
        self.church.save()

    def replace_location(self):
        self.church.location = self.location
        self.church.save()

    def replace_address(self):
        self.church.address = self.address
        self.church.save()

    def replace_zipcode(self):
        self.church.zipcode = self.zipcode
        self.church.save()

    def replace_city(self):
        self.church.city = self.city
        self.church.save()

    def replace_messesinfo_id(self):
        self.church.messesinfo_id = self.messesinfo_id
        self.church.save()

    def replace_parish(self):
        self.church.parish = self.parish
        self.church.save()

    def assign_external_id(self, similar_church_uuid):
        try:
            similar_church = Church.objects.get(uuid=similar_church_uuid)
        except Church.DoesNotExist:
            raise ResourceDoesNotExistError

        if self.source == ExternalSource.MESSESINFO:
            similar_church.messesinfo_id = self.church.messesinfo_id
        else:
            raise NotImplementedError

        self.church.delete()
        similar_church.save()

        # remove moderation CHURCH_DELETED if exists
        ChurchModeration.objects.filter(church=similar_church,
                                        category=self.Category.DELETED_CHURCH,
                                        source=self.source).delete()
