from registry.models import Church
from registry.utils.gouv_fr_utils import geocode_gouv_fr
from registry.utils.string_utils import has_two_consecutive_uppercase


def lower_church_city(church: Church) -> None:
    if church.zipcode and church.city and has_two_consecutive_uppercase(church.city):
        gouv_fr_result = geocode_gouv_fr("", "", church.city, church.zipcode)
        if gouv_fr_result and gouv_fr_result.city \
                and gouv_fr_result.city != church.city:
            church.city = gouv_fr_result.city
            church.save()
