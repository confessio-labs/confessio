import json
from typing import Optional

import requests
from django.contrib.gis.geos import Point

from registry.models import Church, Website, Parish, Diocese
from crawling.utils.url_utils import get_clean_full_url


def post_messesinfo_request(messesinfo_request):
    messesinfo_url = 'https://messes.info/gwtRequest'
    messesinfo_headers = {'content-type': 'application/json; charset=UTF-8'}

    r = requests.post(messesinfo_url, headers=messesinfo_headers, data=messesinfo_request)
    if r.status_code != 200:
        print('messesinfo API error')
        print(r.status_code)
        print(r.text)

        return None

    return r.json()


def fetch_parish(messesinfo_community_id, diocese: Diocese) -> Optional[Parish]:
    messesinfo_request = f'{{"F":"cef.kephas.shared.request.AppRequestFactory",' \
                         f'"I":[{{"O":"cAFxqYS1T1aS3fEnag2PwGf6i9w=",' \
                         f'"P":["{messesinfo_community_id}"],"R":[]}}]}}'
    parish_raw = post_messesinfo_request(messesinfo_request)
    if parish_raw is None:
        print(f'no data for {messesinfo_community_id}')
        return None

    try:
        parish_data = parish_raw['O'][0]['P']
        name = parish_data['name']

        if 'url' in parish_data and parish_data['url']:
            url = parish_data['url']
            home_url = get_clean_full_url(url)  # we use standardized url to ensure unicity
            website = Website(
                name=name,
                home_url=home_url,
            )
        else:
            website = None

        parish = Parish(
            name=name,
            messesinfo_network_id=parish_data['networkId'],
            messesinfo_community_id=parish_data['id'],
            website=website,
            diocese=diocese,
        )

        return parish
    except (KeyError, TypeError) as e:
        print(e)
        print(json.dumps(parish_raw))
        print(messesinfo_community_id)

        return None


def get_parishes_and_churches(messesinfo_network_id: str,
                              diocese: Diocese,
                              filtered_community_id=None,
                              ) -> tuple[list[Parish], list[Church]]:
    page = 0
    churches = []
    parish_by_community_id = {}
    while True:
        churches_request = f'{{"F":"cef.kephas.shared.request.AppRequestFactory",' \
                           f'"I":[{{"O":"$i2wVYlJYdDXj9pOVHx42kKyAu8=",' \
                           f'"P":["DIOCESE:{messesinfo_network_id.upper()}",{page},' \
                           f'25,"48.856614:2.352222",null]}}]}}'

        print(f'fetching churches in {messesinfo_network_id} on page {page}')
        data = post_messesinfo_request(churches_request)

        if data == {"S": [True], "I": [[]]}:
            print('no result')
            break

        for church_raw in data['O']:
            church_data = church_raw['P']
            church_messesinfo_id = church_data['id']

            messesinfo_community_id = church_data['communityId']
            if filtered_community_id and messesinfo_community_id != filtered_community_id:
                continue

            if not church_data['name'] or not church_data['name'].strip():
                print(f'no name for church {church_messesinfo_id}, ignoring this church')
                continue

            parish = parish_by_community_id.get(messesinfo_community_id, None)
            if not parish:
                parish = fetch_parish(messesinfo_community_id, diocese)
                if parish is None:
                    print(
                        f'no valid parish for church {church_messesinfo_id} ignoring this church')
                    continue
                parish_by_community_id[messesinfo_community_id] = parish

            if not church_data['city'] or not church_data['zipcode']:
                print(f'no city or zipcode for church {church_messesinfo_id}, '
                      f'ignoring this church')
                continue

            church = Church(
                name=church_data['name'],
                location=Point(church_data['longitude'], church_data['latitude']),
                address=church_data['address'],
                zipcode=church_data['zipcode'],
                city=church_data['city'],
                messesinfo_id=church_messesinfo_id,
                parish=parish,
            )
            churches.append(church)

        print(f'{len(churches)} churches saved')

        page += 1

    return list(parish_by_community_id.values()), churches
