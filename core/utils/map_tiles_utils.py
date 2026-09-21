import os
import random

JAWG_API_KEY_ENV_VARS = ['JAWG_API_KEY1', 'JAWG_API_KEY2', 'JAWG_API_KEY3']

JAWG_ATTRIBUTION = ('<a href="https://jawg.io" title="Tiles Courtesy of Jawg Maps" '
                    'target="_blank">&copy; <b>Jawg</b>Maps</a> '
                    '&copy; <a href="https://www.openstreetmap.org/copyright">'
                    'OpenStreetMap</a> contributors')


def get_jawg_tiles() -> tuple[str, str]:
    """Return the (url, attribution) of our tile layer, for folium and for django-leaflet.

    OpenStreetMap blocks its free public tiles for us, so every map has to go through Jawg.
    """
    # One key is drawn per map, to spread the free quota over the three accounts.
    api_key = os.environ[random.choice(JAWG_API_KEY_ENV_VARS)]

    return ('https://tile.jawg.io/jawg-sunny/{z}/{x}/{y}{r}.png?access-token=' + api_key,
            JAWG_ATTRIBUTION)
