import json
import time

import httpx

# OClocher sometimes answers 502 transiently
RETRY_DELAYS_SECONDS = (0, 10)


def get_json(client: httpx.Client, url: str) -> list[dict]:
    resp = client.get(url)
    resp.raise_for_status()
    return resp.json()


def fetch_oclocher_url(oclocher_url: str) -> list[dict]:
    timeout = httpx.Timeout(
        connect=10.0,
        read=30.0,
        write=10.0,
        pool=10.0
    )

    with httpx.Client(timeout=timeout) as client:
        for delay in RETRY_DELAYS_SECONDS:
            try:
                return get_json(client, oclocher_url)
            except httpx.HTTPError as e:
                print(f"Request failed, retrying in {delay}s: {e}")
                time.sleep(delay)
        return get_json(client, oclocher_url)


def fetch_organizations() -> list[dict]:
    url = f"https://api.oclocher.fr/organizations/"
    return fetch_oclocher_url(url)


def fetch_organization_locations(oclocher_organization_id: str) -> list[dict]:
    url = f"https://api.oclocher.fr/organizations/{oclocher_organization_id}/locations"
    return fetch_oclocher_url(url)


def fetch_organization_schedules(oclocher_organization_id: str):
    url = f"https://api.oclocher.fr/organizations/{oclocher_organization_id}/schedules"
    all_schedules = fetch_oclocher_url(url)

    # filter only confession
    return [
        schedule for schedule in all_schedules
        if schedule.get('selection') == 'confession'
    ]


if __name__ == '__main__':
    print(json.dumps(fetch_organization_schedules("ltkAShJzN8YHzl9FtxgD")))
    print(json.dumps(fetch_organization_locations("ltkAShJzN8YHzl9FtxgD")))
