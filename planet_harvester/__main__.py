import hashlib
import json
import logging
import os

import boto3
import requests
from botocore.exceptions import ClientError
from eodhp_utils.aws.s3 import upload_file_s3
from eodhp_utils.runner import get_boto3_session, get_pulsar_client, setup_logging

from planet_harvester.response_adaptor import planet_to_stac_response_collection

from .planet_harvester_messager import PlanetHarvesterMessager

setup_logging()

minimum_message_entries = int(os.environ.get("MINIMUM_MESSAGE_ENTRIES", 100))


def get_collections() -> dict:
    """Get collections from Planet"""

    api_key = os.environ.get("PLANET_API_KEY")

    planet_response = requests.get(
        "https://api.planet.com/data/v1/item-types", auth=requests.auth.HTTPBasicAuth(api_key, "")
    )

    all_collections = planet_to_stac_response_collection(planet_response=planet_response.json())

    collections = remove_unused_collections(all_collections)

    return collections


def remove_unused_collections(collections: dict) -> dict:
    unused_collections = os.environ.get("UNUSED_COLLECTIONS", "").split(",")

    all_collections = collections["collections"]
    remaining_collections = []

    for collection in all_collections:
        if collection["id"] not in unused_collections:
            remaining_collections.append(collection)

    collections["collections"] = remaining_collections

    return collections


def compare_to_previous_version(
    key: str,
    data: str,
    previous_hash: str,
    harvested_keys: dict,
    s3_bucket: str,
    s3_client: boto3.session.Session.client,
) -> tuple:
    """Compares a file to a previous version of a file as determined by the hash. New or updated
    files are uploaded to S3"""
    file_hash = get_file_hash(data)

    if not previous_hash:
        # URL was not harvested previously
        logging.info(f"Added: {key}")
        harvested_keys["added_keys"].add(key)
        upload_file_s3(data, s3_bucket, key, s3_client)
    elif previous_hash != file_hash:
        # URL has changed since last run
        logging.info(f"Updated: {key}")
        harvested_keys["updated_keys"].add(key)
        upload_file_s3(data, s3_bucket, key, s3_client)

    return harvested_keys, file_hash


def get_file_hash(data: str) -> str:
    """Returns hash of data available"""

    def _md5_hash(byte_str: bytes) -> str:
        """Calculates an md5 hash for given bytestring"""
        md5 = hashlib.md5()
        md5.update(byte_str)
        return md5.hexdigest()

    return _md5_hash(data.encode("utf-8"))


def get_file_s3(bucket: str, key: str, s3_client: boto3.client) -> str:
    """Retrieve data from an S3 bucket"""
    try:
        file_obj = s3_client.get_object(Bucket=bucket, Key=key)
        return file_obj["Body"].read().decode("utf-8")
    except ClientError as e:
        logging.warning(f"File retrieval failed for {key}: {e}")
        return None


def get_metadata(bucket: str, key: str, s3_client: boto3.client) -> dict:
    """Read file at given S3 location and parse as JSON"""
    previously_harvested = get_file_s3(bucket, key, s3_client)
    try:
        previously_harvested = json.loads(previously_harvested)
    except TypeError:
        previously_harvested = {}
    return previously_harvested


def make_catalogue() -> str:
    """Top level catalogue for Planet data"""
    stac_catalog = {
        "type": "Catalog",
        "id": "planet",
        "stac_version": "1.0.0",
        "description": "Planet Datasets",
        "links": [],
    }
    return json.dumps(stac_catalog, indent=4)


def main():
    s3_client = get_boto3_session().client("s3")

    s3_bucket = os.getenv("S3_BUCKET")

    harvested_data = {}

    logging.info("Harvesting from Planet")

    key_root = "supported-datasets/planet"

    pulsar_client = get_pulsar_client()
    producer = pulsar_client.create_producer(
        topic="harvested", producer_name="stac_harvester/planet", chunking_enabled=True
    )

    planet_harvester_messager = PlanetHarvesterMessager(
        s3_client=s3_client,
        output_bucket=s3_bucket,
        cat_output_prefix="git-harvester/",
        producer=producer,
    )

    metadata_s3_key = "harvested-metadata/planet"
    previously_harvested = get_metadata(s3_bucket, metadata_s3_key, s3_client)
    logging.info(f"Previously harvested URLs: {previously_harvested}")

    latest_harvested = {}

    catalogue_data = make_catalogue()
    catalogue_key = "supported-datasets/planet.json"
    previous_hash = previously_harvested.pop(catalogue_key, None)

    file_hash = get_file_hash(json.dumps(catalogue_data))
    previous_hash = previously_harvested.pop(catalogue_key, None)
    if not previous_hash or previous_hash != file_hash:
        # URL was not harvested previously
        logging.info(f"Added: {catalogue_key}")
        harvested_data[catalogue_key] = catalogue_data
        latest_harvested[catalogue_key] = file_hash

    collections = get_collections()["collections"]

    print(collections)

    for collection in collections:
        collection_id = collection["id"]

        file_name = f"{collection_id}.json"
        collection_key = f"{key_root}/{file_name}"

        file_hash = get_file_hash(json.dumps(collection))
        previous_hash = previously_harvested.pop(collection_key, None)
        if not previous_hash or previous_hash != file_hash:
            # URL was not harvested previously
            logging.info(f"Added: {collection_key}")
            harvested_data[collection_key] = collection
            latest_harvested[collection_key] = file_hash

    deleted_keys = list(previously_harvested.keys())

    # Send message for altered keys
    msg = {
        "harvested_data": harvested_data,
        "deleted_keys": deleted_keys,
        "latest_harvested": {"data": latest_harvested, "metadata_s3_key": metadata_s3_key},
    }
    planet_harvester_messager.consume(msg)


if __name__ == "__main__":
    main()
