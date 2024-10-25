def map_collection(collection):

    return {
        "type": "Collection",
        "id": collection["id"],
        "stac_version": "1.0.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/sar/v1.0.0/schema.json",
        ],
        "description": (collection["display_description"]),
        "links": [],
        "title": collection["display_name"],
        "geometry": {"type": "Polygon"},
        "extent": {
            "spatial": {"bbox": [-180, -90, 90, 180]},
            "temporal": {"interval": [0, 0]},
        },
        "license": "proprietary",
        "keywords": ["planet", collection["id"]],
        "summaries": {},
        "item_assets": {
            "thumbnail": {
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "roles": ["thumbnail"],
                "title": "Thumbnail Image",
            }
        },
    }


def planet_to_stac_response_collection(planet_response: dict):
    stac_collections = []

    for planet_collection in planet_response["item_types"]:
        stac_collections.append(map_collection(planet_collection))

    return {"collections": stac_collections}
