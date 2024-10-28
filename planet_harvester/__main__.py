import hashlib
import json
import logging
import os

import boto3
import click
import requests
from botocore.exceptions import ClientError
from eodhp_utils.aws.s3 import upload_file_s3
from pulsar import Client as PulsarClient

from planet_harvester.response_adaptor import planet_to_stac_response_collection

logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG") else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler()],
)

minimum_message_entries = int(os.environ.get("MINIMUM_MESSAGE_ENTRIES", 100))


@click.group()
# you can implement any global flags here that will apply to all commands, e.g. debug
# @click.option('--debug/--no-debug', default=False) # don't feel the need to implement this, just an example
def cli():
    """This is just a placeholder to act as the entrypoint, you can do things with global options here
    if required"""
    pass


@cli.command()
# not currently used but keeping the same structure as the other harvester repos
# @click.argument("source_url", type=str, nargs=1)
@click.argument("workspace_name", type=str)
@click.argument(
    "catalog", type=str
)  # not currently used but keeping the same structure as the other harvester repos
@click.argument("s3_bucket", type=str)
def harvest(workspace_name: str, catalog: str, s3_bucket: str):
    """Harvest Planet catalogues at the top level. Send a pulsar message
    containing all added, updated, and deleted links since the last time the catalog was
    harvested"""

    if os.getenv("AWS_ACCESS_KEY") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        session = boto3.session.Session(
            aws_access_key_id=os.environ["AWS_ACCESS_KEY"],
            aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        )
        s3_client = session.client("s3")
    else:
        s3_client = boto3.client("s3")

    pulsar_url = os.environ.get("PULSAR_URL")
    pulsar_client = PulsarClient(pulsar_url)

    harvested_keys = {"added_keys": set(), "updated_keys": set()}

    logging.info("Harvesting from Planet")

    key_root = "git-harvester/supported-datasets/planet"

    metadata_s3_key = "harvested-metadata/planet"
    previously_harvested = get_metadata(s3_bucket, metadata_s3_key, s3_client)
    logging.info(f"Previously harvested URLs: {previously_harvested}")
    latest_harvested = {}

    catalogue_data = make_catalogue()
    catalogue_key = "git-harvester/supported-datasets/planet.json"
    previous_hash = previously_harvested.pop(catalogue_key, None)
    harvested_keys, latest_harvested[catalogue_key] = compare_to_previous_version(
        catalogue_key, catalogue_data, previous_hash, harvested_keys, s3_bucket, s3_client
    )

    collections = get_collections()["collections"]

    for collection in collections:
        collection_id = collection["id"]

        file_name = f"{collection_id}.json"
        collection_key = f"{key_root}/{file_name}"

        previous_hash = previously_harvested.pop(collection_key, None)
        harvested_keys, latest_harvested[collection_key] = compare_to_previous_version(
            collection_key,
            json.dumps(collection),
            previous_hash,
            harvested_keys,
            s3_bucket,
            s3_client,
        )

    upload_file_s3(json.dumps(latest_harvested), s3_bucket, metadata_s3_key, s3_client)

    deleted_keys = list(previously_harvested.keys())
    output_data = {
        "id": f"{workspace_name}/planet",
        "workspace": workspace_name,
        "bucket_name": s3_bucket,
        "added_keys": list(harvested_keys["added_keys"]),
        "updated_keys": list(harvested_keys["updated_keys"]),
        "deleted_keys": deleted_keys,
        "source": "planet",
        "target": "/",
    }

    if any([harvested_keys["added_keys"], harvested_keys["updated_keys"], deleted_keys]):
        # Send Pulsar message containing harvested links
        send_pulsar_message(output_data, pulsar_client)
        logging.info(f"Sent harvested message {output_data}")
    else:
        logging.info("No changes made to previously harvested state")

    return output_data


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


def send_pulsar_message(output_data: dict, pulsar_client: PulsarClient) -> None:
    """Sends pulsar message for a given set of output data"""

    producer = pulsar_client.create_producer(
        topic="harvested", producer_name="stac_harvester/planet", chunking_enabled=True
    )
    producer.send((json.dumps(output_data)).encode("utf-8"))
    producer.close()
    logging.info(f"Sent harvested message {output_data}")


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


if __name__ == "__main__":
    cli(obj={})
