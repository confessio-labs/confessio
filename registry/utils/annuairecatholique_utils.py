import json
import os
import time
from datetime import datetime

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError, field_validator

DEFAULT_BASE_URL = 'https://annuaire-catholique-api.touchard.bzh'


class AnnuaireCatholiquePosition(BaseModel):
    latitude: float
    longitude: float


class AnnuaireCatholiqueCommune(BaseModel):
    code_insee: str
    name: str


class AnnuaireCatholiqueMessesInfo(BaseModel):
    id: str
    id_fixe: str | None = None
    locality_id: int | None = None


class AnnuaireCatholiquePlace(BaseModel):
    id: str  # UUID
    business_id: str
    name: str | None = None
    wikidata_id: str | None = None
    position: AnnuaireCatholiquePosition | None = None
    commune: AnnuaireCatholiqueCommune | None = None
    messes_info: list[AnnuaireCatholiqueMessesInfo] = []
    updated_at: datetime
    created_at: datetime

    @field_validator('messes_info', mode='before')
    @classmethod
    def _none_to_empty_list(cls, value):
        return value or []


def _base_url() -> str:
    return os.getenv('ANNUAIRECATHOLIQUE_API_URL', DEFAULT_BASE_URL).rstrip('/')


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    # The API does not send Retry-After today, but honor it if it ever does.
    retry_after = response.headers.get('Retry-After')
    if retry_after:
        try:
            return min(float(int(retry_after)), 30.0)
        except ValueError:
            pass
    # Adaptive exponential backoff (the limiter refills ~0.6s/token).
    return min(1.0 * 2 ** attempt, 30.0)


def fetch_annuairecatholique(url: str, params: dict | None = None,
                             max_retries: int = 5) -> dict | None:
    for attempt in range(max_retries + 1):
        try:
            response = httpx.get(url, params=params, timeout=5.0)

            if response.status_code == 404:
                print(f'Found 404 for URL: {url}')
                return None

            if response.status_code == 429:
                if attempt == max_retries:
                    print(f"Annuairecatholique rate limited (429), giving up on {url}")
                    return None
                wait = _retry_after_seconds(response, attempt)
                print(f"Annuairecatholique rate limited (429), waiting {wait:.1f}s ...")
                time.sleep(wait)
                continue

            response.raise_for_status()
            data = response.json()

            if not data:
                return None

            return data

        except httpx.HTTPStatusError as e:
            print(f"Annuairecatholique GET API HTTP error: {e}")
            return None

        except httpx.ReadTimeout as e:
            print(f"Annuairecatholique GET API ReadTimeout error: {e}")
            return None

    return None


def fetch_places(page: int = 1, page_size: int = 50, order_by: str = 'updated_at',
                 order_dir: str = 'desc', commune: str | None = None,
                 wikidata_id: str | None = None
                 ) -> tuple[list[AnnuaireCatholiquePlace], int]:
    """Returns (places, total_pages) from GET {base}/api/places."""
    url = f'{_base_url()}/api/places'
    params = {
        'page': page,
        'page_size': page_size,
        'order_by': order_by,
        'order_dir': order_dir,
    }
    if commune:
        params['commune'] = commune
    if wikidata_id:
        params['wikidata_id'] = wikidata_id

    data = fetch_annuairecatholique(url, params=params)
    if not data:
        return [], 0

    places = []
    for item in data.get('data', []):
        try:
            places.append(AnnuaireCatholiquePlace(**item))
        except ValidationError as e:
            print(f"Validation error while parsing annuairecatholique place: {e}")
            print(json.dumps(item))

    return places, data.get('total_pages', 0)


def fetch_place_by_id(place_id: str) -> AnnuaireCatholiquePlace | None:
    """Returns a single place from GET {base}/api/places/{place_id} (404 -> None)."""
    url = f'{_base_url()}/api/places/{place_id}'
    data = fetch_annuairecatholique(url)
    if not data:
        return None

    try:
        return AnnuaireCatholiquePlace(**data)
    except ValidationError as e:
        print(f"Validation error while parsing annuairecatholique place: {e}")
        print(json.dumps(data))
        return None


if __name__ == '__main__':
    load_dotenv()
    print(fetch_places(page_size=1))
