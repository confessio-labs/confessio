from urllib.parse import quote

import requests
from pydantic import BaseModel, Field
from requests import RequestException, JSONDecodeError


class GouvFrGeocodingResult(BaseModel):
    coordinates_latlon: tuple[float, float] | None
    address: str | None
    city: str | None
    zipcode: str | None


def geocode_gouv_fr(name, address, city, zipcode) -> GouvFrGeocodingResult | None:
    query = f"q={quote(' '.join(filter(lambda s: s is not None and s, [name, address, city])))}"
    if zipcode:
        query += f'&postcode={zipcode}'

    url = f'https://api-adresse.data.gouv.fr/search/?{query}'

    try:
        print('geocoding with url', url)
        r = requests.get(url)
    except RequestException as e:
        print(e)
        return None

    if r.status_code != 200:
        print(r.status_code)
        print(r.text)
        return None

    try:
        data = r.json()
    except JSONDecodeError as e:
        print('invalid json response', e)
        print(r.text)
        return None

    if 'features' not in data or not data['features']:
        print('got no geocoding results', data)
        return None

    feature = data['features'][0]
    coordinates = feature.get('geometry', {}).get('coordinates', None)
    coordinates_latlon = (coordinates[1], coordinates[0]) if coordinates else None
    zipcode = feature.get('properties', {}).get('postcode', None)
    city = feature.get('properties', {}).get('city', None)
    address = feature.get('properties', {}).get('name', None)

    return GouvFrGeocodingResult(
        coordinates_latlon=coordinates_latlon,
        address=address,
        city=city,
        zipcode=zipcode
    )


class GouvFrCommune(BaseModel):
    nom: str
    code: str
    zipcodes: list[str] = Field(default_factory=list, alias='codesPostaux')
    population: int | None = None
    centre: dict | None = None


def fetch_communes() -> list[GouvFrCommune]:
    """Fetches every current French commune (~35k, ~5 MB).

    `type=commune-actuelle` is the API default, but passing it explicitly guarantees that
    arrondissements municipaux (Paris 1er, Lyon 3e, ...) stay out: Paris, Lyon and Marseille
    are each returned once, with all their arrondissement zipcodes aggregated.
    """
    url = ('https://geo.api.gouv.fr/communes'
           '?fields=nom,code,codesPostaux,population,centre&type=commune-actuelle')

    try:
        r = requests.get(url, timeout=120)
    except RequestException as e:
        print('error while fetching communes', e)
        return []

    if r.status_code != 200:
        print(r.status_code)
        print(r.text[:500])
        return []

    try:
        data = r.json()
    except JSONDecodeError as e:
        print('invalid json response', e)
        print(r.text[:500])
        return []

    return [GouvFrCommune(**item) for item in data]


if __name__ == '__main__':
    # print(geocode_gouv_fr("Chapelle de l'école Saint-Joseph", "18 route d'Ecully",
    #                       "Dardilly", 69570))
    print(geocode_gouv_fr("", "", "Boulogne", 92100))
