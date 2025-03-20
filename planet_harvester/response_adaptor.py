import logging
import os
from json import JSONDecodeError
from typing import Optional

import requests


def get_date_range(collection: dict, retries=0) -> list:
    """Gets date range for a given Planet collection"""
    collection_id = collection["id"]

    dates = []

    for modifier in ["", "-"]:
        url = (
            f"{os.environ['PLANET_API_URL']}/search?collections={collection_id}"
            f"&limit=1"
            f"&sortby={modifier}published"
        )
        try:
            response = requests.get(url)
        except (JSONDecodeError, requests.exceptions.HTTPError):
            logging.warning(f"Retrying retrieval of {url}. Attempt {retries}")
            if retries > 3:
                raise

            return get_date_range(collection, retries=retries + 1)

        all_data = response.json()
        try:
            date = all_data["features"][0]["properties"].get("datetime", "1970-01-01T00:00:00.000Z")
        except IndexError:
            logging.info(
                f"No entries found for collection {collection_id}. " f"Collection not added"
            )
            return None

        dates.append(date)

    return dates


def map_description(collection) -> str:
    """Obtain a description for a collection"""
    descriptions_map = {
        "SkySatCollect": (
            "SkySat, operated by Planet, is a high resolution constellation of 15 satellites, able "
            "to image revisit any location on Earth up to 10x daily (a daily collection capacity "
            "of 4,000 km2/day).  SkySat produces 4-band (blue, green, red, NIR) and panchromatic "
            "imagery  and is sampled at 50 centimeters per pixel when orthorectified. Skysat "
            "Collect provides coregistered, stacked, mosaiced scenes."
        ),
        "PSScene": (
            "PlanetScope, operated by Planet, is a constellation of approximately 130 satellites, "
            "able to image the entire land surface of the Earth every day (a daily collection "
            "capacity of 200 million km²/day). PlanetScope images are approximately 3 meters per "
            "pixel resolution. The PlanetScope satellite constellation consists of multiple "
            'launches ("flocks") of Dove satellites.  PlanetScope Scenes are either Four band '
            "(RGBNIR), or Eight band (RGBNIR, red edge, green I, yellow and coastal blue), "
            "depending on which generation of satellite the product was acquired by. On-orbit "
            "capacity is constantly improving in capability and quantity, with technology "
            "improvements deployed at a rapid pace."
        ),
    }

    collection_id = collection["id"]
    return descriptions_map.get(collection_id, collection["display_description"])


def map_keywords(collection) -> list:
    """Obtain a list of keywords for a collection"""
    keywords_map = {
        "SkySatCollect": [
            "Optical",
            "High-res",
            "SkySat",
        ],
        "PlanetScope": [
            "Optical",
            "PlanetScope",
        ],
    }

    collection_id = collection["id"]
    return keywords_map.get(collection_id, [])


def map_thumbnail(collection) -> Optional[str]:
    """Obtain a thumbnail for a collection"""
    thumbnails_map = {
        "SkySatCollect": "https://planet.widen.net/s/ffdfpftdfb/falmouth-cornwall-united-kingdom_20240305_s116_rgb_50cm_rotated45_5200px",
        "PlanetScope": "https://planet.widen.net/s/v22fmxpcws/glastonbury_somerset_england_20240626_111854_75_24e1_3b_visual_clip",
    }

    collection_id = collection["id"]
    return thumbnails_map.get(collection_id, None)


def map_collection(collection, dates):
    start_date, end_date = dates
    stac_collection = {
        "type": "Collection",
        "id": collection["id"],
        "stac_version": "1.0.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/sar/v1.0.0/schema.json",
        ],
        "description": map_description(collection),
        "links": [],
        "title": collection["display_name"],
        "geometry": {"type": "Polygon"},
        "extent": {
            "spatial": {"bbox": [[-180, -90, 90, 180]]},
            "temporal": {"interval": [[start_date, end_date]]},
        },
        "license": "proprietary",
        "keywords": ["Planet"] + map_keywords(collection),
        "summaries": {},
        "item_assets": {
            "thumbnail": {
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "roles": ["thumbnail"],
                "title": "Thumbnail Image",
            }
        },
    }
    if thumbnail := map_thumbnail(collection):
        stac_collection["assets"] = {
            "thumbnail": {"href": thumbnail, "type": "image/jpeg", "roles": ["thumbnail"]}
        }
    return stac_collection


def planet_to_stac_response_collection(planet_response: dict):
    stac_collections = []

    for planet_collection in planet_response["item_types"]:
        dates = get_date_range(planet_collection)
        if dates:
            formatted_collection = map_collection(planet_collection, dates)

            stac_collections.append(formatted_collection)

    return {"collections": stac_collections}
