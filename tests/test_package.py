import json
import os
from unittest import mock
from unittest.mock import patch

import boto3
import moto
import pytest
from click.testing import CliRunner

from planet_harvester.__main__ import get_collections, harvest


@pytest.fixture(autouse=True)
def setenvvar(monkeypatch):
    with mock.patch.dict(os.environ, clear=True):
        envvars = {
            "PLANET_API_KEYS": "Pl4n3t-4p1-k3y-1:Pl4n3t-4p1-k3y-2",
            "PLANET_API_URL": "https://planet.api.com",
            "VALID_COLLECTIONS": "SkySatVideo,TanagerScene,TanagerMethane"
        }
        for k, v in envvars.items():
            monkeypatch.setenv(k, v)
        yield


@pytest.fixture
def mock_catalogue_response():
    return {
        "_links": {"_self": "https://api.planet.com/data/v1/item-types/"},
        "item_types": [
            {
                "_links": {"_self": "https://api.planet.com/data/v1/item-types/SkySatVideo"},
                "display_description": "SkySat video product",
                "display_name": "SkySat Video",
                "id": "SkySatVideo",
                "supported_asset_types": ["video_file", "video_frames", "video_metadata"],
            },
            {
                "_links": {"_self": "https://api.planet.com/data/v1/item-types/TanagerScene"},
                "display_description": "Tanager Hyperspectral Imagery",
                "display_name": "Tanager Scene",
                "id": "TanagerScene",
                "supported_asset_types": [
                    "basic_beta_udm",
                    "basic_radiance_hdf5",
                    "basic_sr_hdf5",
                    "geolocation_array",
                    "ortho_beta_udm",
                    "ortho_radiance_hdf5",
                    "ortho_sr_hdf5",
                    "ortho_visual",
                ],
            },
            {
                "_links": {"_self": "https://api.planet.com/data/v1/item-types/TanagerMethane"},
                "display_description": "Tanager Methane Derived Products",
                "display_name": "Tanager Methane",
                "id": "TanagerMethane",
                "supported_asset_types": [
                    "ql_ch4_json",
                    "qc_ch4_json",
                    "ime_ch4_json",
                    "ortho_ql_ch4",
                    "ortho_qc_ch4",
                    "ortho_ime_ch4",
                    "recent_monthly_basemap",
                ],
            },
        ],
    }


@pytest.fixture
def mock_catalogue_search_response():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "bbox": [8.282253923374252, 6.382697782768316, 8.584244575686702, 6.59739514795537],
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [8.314056396687644, 6.59739514795537],
                            [8.282253923374252, 6.435883797769592],
                            [8.552442923758617, 6.382697782768316],
                            [8.584244575686702, 6.544004759818029],
                            [8.314056396687644, 6.59739514795537],
                        ]
                    ],
                },
                "properties": {
                    "title": None,
                    "datetime": "2024-11-28T09:22:53.523234Z",
                    "updated": "2024-11-28T13:02:18Z",
                    "acquired": "2024-11-28T09:22:53.523234Z",
                    "published": "2024-11-28T13:02:18Z",
                },
                "id": "20241128_092253_52_24c4",
                "stac_version": "1.0.0",
                "assets": {},
                "links": [],
                "stac_extensions": [],
                "collection": "PSScene",
            }
        ],
        "links": [],
    }


@moto.mock_aws
@patch("planet_harvester.__main__.get_pulsar_client")
@patch.dict("os.environ", {"S3_BUCKET": "my-bucket", "PULSAR_URL": "mypulsar.com/pulsar"})
def test_harvest(
    mock_create_client, requests_mock, mock_catalogue_response, mock_catalogue_search_response
):
    requests_mock.get(
        "https://api.planet.com/data/v1/item-types",
        text=json.dumps(mock_catalogue_response),
    )
    for collection in ["SkySatVideo", "TanagerScene", "TanagerMethane"]:
        requests_mock.get(
            f"https://planet.api.com/search?collections={collection}&limit=1&sortby=published",
            text=json.dumps(mock_catalogue_search_response),
        )
        requests_mock.get(
            f"https://planet.api.com/search?collections={collection}&limit=1&sortby=-published",
            text=json.dumps(mock_catalogue_search_response),
        )

    mock_client = mock.MagicMock()
    mock_producer = mock.MagicMock()
    mock_create_client.return_value = mock_client
    mock_client.create_producer.return_value = mock_producer

    bucket_name = "my-bucket"

    s3 = boto3.resource("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=bucket_name)

    runner = CliRunner()
    runner.invoke(harvest, f"workspace catalogue {bucket_name}".split())

    s3 = boto3.resource("s3")
    my_bucket = s3.Bucket(bucket_name)

    assert len(list(my_bucket.objects.all())) == 5

    args, kwargs = mock_producer.send.call_args
    call_args = json.loads(args[0])
    assert {
        "id",
        "workspace",
        "bucket_name",
        "added_keys",
        "updated_keys",
        "deleted_keys",
        "source",
        "target",
    }.issubset(call_args.keys())
    assert call_args["bucket_name"] == bucket_name
    assert len(call_args["added_keys"]) == 4
    assert len(call_args["updated_keys"]) == len(call_args["deleted_keys"]) == 0


@moto.mock_aws
@patch("planet_harvester.__main__.PlanetHarvesterMessager.consume")
@patch("planet_harvester.__main__.get_pulsar_client")
@patch.dict("os.environ", {"S3_BUCKET": "my-bucket", "PULSAR_URL": "mypulsar.com/pulsar"})
def test_harvest_expected_calls(
    mock_create_client,
    mock_planet_messager_consume,
    requests_mock,
    mock_catalogue_response,
    mock_catalogue_search_response,
):
    requests_mock.get(
        "https://api.planet.com/data/v1/item-types",
        text=json.dumps(mock_catalogue_response),
    )
    mock_planet_messager_consume.return_value = None

    for collection in ["SkySatVideo", "TanagerScene", "TanagerMethane"]:
        requests_mock.get(
            f"https://planet.api.com/search?collections={collection}&limit=1&sortby=published",
            text=json.dumps(mock_catalogue_search_response),
        )
        requests_mock.get(
            f"https://planet.api.com/search?collections={collection}&limit=1&sortby=-published",
            text=json.dumps(mock_catalogue_search_response),
        )

    mock_client = mock.MagicMock()
    mock_producer = mock.MagicMock()
    mock_create_client.return_value = mock_client
    mock_client.create_producer.return_value = mock_producer

    bucket_name = "my-bucket"

    s3 = boto3.resource("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=bucket_name)

    runner = CliRunner()
    runner.invoke(harvest, f"workspace catalogue {bucket_name}".split())

    mock_planet_messager_consume.assert_called_once()


def test_get_collections(mock_catalogue_response, requests_mock, mock_catalogue_search_response):
    requests_mock.get(
        "https://api.planet.com/data/v1/item-types",
        text=json.dumps(mock_catalogue_response),
    )
    for collection in ["SkySatVideo", "TanagerScene", "TanagerMethane"]:
        requests_mock.get(
            f"https://planet.api.com/search?collections={collection}&limit=1&sortby=published",
            text=json.dumps(mock_catalogue_search_response),
        )
        requests_mock.get(
            f"https://planet.api.com/search?collections={collection}&limit=1&sortby=-published",
            text=json.dumps(mock_catalogue_search_response),
        )

    collections = get_collections()

    assert len(mock_catalogue_response["item_types"]) == len(collections["collections"])

    for i in range(len(mock_catalogue_response["item_types"])):
        assert mock_catalogue_response["item_types"][i]["id"] == collections["collections"][i]["id"]


def test_remove_invalid_collections(
    mock_catalogue_response, requests_mock, mock_catalogue_search_response
):

    requests_mock.get(
        "https://api.planet.com/data/v1/item-types",
        text=json.dumps(mock_catalogue_response),
    )
    for collection in ["SkySatVideo", "TanagerScene", "TanagerMethane"]:
        requests_mock.get(
            f"https://planet.api.com/search?collections={collection}&limit=1&sortby=published",
            text=json.dumps(mock_catalogue_search_response),
        )
        requests_mock.get(
            f"https://planet.api.com/search?collections={collection}&limit=1&sortby=-published",
            text=json.dumps(mock_catalogue_search_response),
        )

    test_collections = "TanagerScene"

    with mock.patch.dict(os.environ, {"VALID_COLLECTIONS": test_collections}):
        collections = get_collections()
        print(len(collections['collections']))
        print((collections))

    assert len(mock_catalogue_response["item_types"]) == len(collections["collections"]) + 2

    for i in range(len(collections["collections"])):
        assert collections["collections"][i]["id"] in test_collections.split(",")
