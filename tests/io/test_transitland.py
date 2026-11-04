"""Tests for the Transitland API client."""


import io
import zipfile
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from netweave.exceptions import NoFeedsFoundError, TransitlandAPIError
from netweave.io.gtfs import GTFSFeed
from netweave.io.transitland import (
    _bbox_to_string,
    _get_api_key,
    _parse_feeds,
    download_feed,
    fetch_feeds,
    search_feeds,
    transit_network_from_transitland,
)
from netweave.types import TransitNetwork

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_api_key(monkeypatch):
    """Set a dummy TRANSITLAND_API_KEY environment variable."""
    monkeypatch.setenv("TRANSITLAND_API_KEY", "test_key_123")
    yield
    monkeypatch.delenv("TRANSITLAND_API_KEY", raising=False)


@pytest.fixture
def sample_feed_response():
    """Return a sample Transitland feed search response."""
    return {
        "feeds": [
            {
                "id": 1,
                "onestop_id": "f-sf~bay~area~rg",
                "name": "Bay Area Rapid Transit",
                "spec": "gtfs",
                "urls": {
                    "static_current": "https://example.com/bart.zip",
                    "static_historic": [],
                },
                "license": {
                    "spdx_identifier": "CC-BY-4.0",
                    "url": "https://example.com/license",
                    "redistribution_allowed": "yes",
                    "commercial_use_allowed": "yes",
                    "create_derived_product": "yes",
                },
                "feed_state": {"fetched_at": "2024-01-01T00:00:00Z"},
            },
            {
                "id": 2,
                "onestop_id": "f-sf~muni",
                "name": "SF Muni",
                "spec": "gtfs",
                "urls": {
                    "static_current": "https://example.com/muni.zip",
                    "static_historic": [],
                },
                "license": {
                    "redistribution_allowed": "yes",
                },
                "feed_state": {},
            },
        ],
        "meta": {"after": None},
    }


@pytest.fixture
def sample_feed_response_paginated():
    """Return a paginated feed search response (page 1 of 2)."""
    return {
        "feeds": [
            {
                "id": 1,
                "onestop_id": "f-page1",
                "name": "Page 1 Feed",
                "spec": "gtfs",
                "urls": {"static_current": "https://example.com/p1.zip"},
                "license": {"redistribution_allowed": "yes"},
                "feed_state": {},
            },
        ],
        "meta": {"after": 999},
    }


@pytest.fixture
def empty_feed_response():
    """Return an empty feed search response."""
    return {"feeds": [], "meta": {"after": None}}


@pytest.fixture
def mock_gtfs_zip_bytes(minimal_gtfs_feed):
    """Return a GTFS zip file as bytes from a minimal feed."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for attr in [
            "agency", "routes", "trips", "stop_times", "stops", "calendar",
        ]:
            df = getattr(minimal_gtfs_feed, attr)
            if not df.empty:
                csv_bytes = df.to_csv(index=False).encode("utf-8")
                zf.writestr(f"{attr}.txt", csv_bytes)
    buffer.seek(0)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# _get_api_key
# ---------------------------------------------------------------------------


class TestGetApiKey:
    def test_from_parameter(self):
        assert _get_api_key("my_key") == "my_key"

    @pytest.mark.usefixtures("mock_api_key")
    def test_from_env(self):
        assert _get_api_key() == "test_key_123"

    @pytest.mark.usefixtures("mock_api_key")
    def test_parameter_overrides_env(self):
        assert _get_api_key("override_key") == "override_key"

    def test_missing_raises(self, monkeypatch):
        monkeypatch.delenv("TRANSITLAND_API_KEY", raising=False)
        with pytest.raises(TransitlandAPIError, match="API key is required"):
            _get_api_key()


# ---------------------------------------------------------------------------
# _bbox_to_string
# ---------------------------------------------------------------------------


class TestBboxToString:
    def test_basic(self):
        bbox = (-122.5, 37.7, -122.4, 37.8)
        assert _bbox_to_string(bbox) == "-122.5,37.7,-122.4,37.8"

    def test_negative_values(self):
        bbox = (18.3, -33.9, 18.5, -33.8)
        assert _bbox_to_string(bbox) == "18.3,-33.9,18.5,-33.8"


# ---------------------------------------------------------------------------
# _parse_feeds
# ---------------------------------------------------------------------------


class TestParseFeeds:
    def test_empty(self):
        df = _parse_feeds([])
        assert df.empty

    def test_basic(self, sample_feed_response):
        df = _parse_feeds(sample_feed_response["feeds"])
        assert len(df) == 2
        assert list(df.columns) == [
            "feed_key", "onestop_id", "name", "spec", "static_current",
            "static_historic", "realtime_vehicle_positions", "realtime_trip_updates",
            "realtime_alerts", "license_spdx", "license_url",
            "license_redistribution", "license_commercial", "license_create_derived",
            "feed_state",
        ]
        assert df.loc[0, "feed_key"] == 1
        assert df.loc[0, "onestop_id"] == "f-sf~bay~area~rg"
        assert df.loc[0, "license_redistribution"] == "yes"


# ---------------------------------------------------------------------------
# search_feeds
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("mock_api_key")
class TestSearchFeeds:
    @patch("netweave.io.transitland._request")
    def test_by_bbox(self, mock_request, sample_feed_response):
        # First call is /stops verification, second is /feeds search
        stops_response = {
            "stops": [
                {"feed_version": {"feed": {"onestop_id": "f-sf~bay~area~rg"}}},
                {"feed_version": {"feed": {"onestop_id": "f-sf~muni"}}},
            ],
            "meta": {"after": None},
        }
        mock_request.side_effect = [stops_response, sample_feed_response]
        df = search_feeds(bbox=(-122.5, 37.7, -122.4, 37.8))
        assert len(df) == 2
        assert mock_request.call_count == 2
        # First call should be to /stops
        assert "stops" in mock_request.call_args_list[0][0][0]
        # Second call should be to /feeds
        _, params, _ = mock_request.call_args_list[1][0]
        assert params["bbox"] == "-122.5,37.7,-122.4,37.8"
        assert params["spec"] == "gtfs"

    @patch("netweave.io.transitland._request")
    def test_by_search(self, mock_request, sample_feed_response):
        mock_request.return_value = sample_feed_response
        df = search_feeds(search="caltrain")
        assert len(df) == 2
        _, params, _ = mock_request.call_args[0]
        assert params["search"] == "caltrain"

    @patch("netweave.io.transitland._request")
    def test_pagination(self, mock_request, sample_feed_response_paginated):
        page2 = {
            "feeds": [
                {
                    "id": 2,
                    "onestop_id": "f-page2",
                    "name": "Page 2 Feed",
                    "spec": "gtfs",
                    "urls": {"static_current": "https://example.com/p2.zip"},
                    "license": {"redistribution_allowed": "yes"},
                    "feed_state": {},
                },
            ],
            "meta": {"after": None},
        }
        mock_request.side_effect = [sample_feed_response_paginated, page2]
        df = search_feeds(search="test", limit=100)
        assert len(df) == 2
        assert mock_request.call_count == 2

    @patch("netweave.io.transitland._request")
    def test_no_results_raises(self, mock_request, empty_feed_response):
        mock_request.return_value = empty_feed_response
        with pytest.raises(NoFeedsFoundError, match="No GTFS feeds found"):
            search_feeds(search="nonexistent")

    def test_no_filter_raises(self):
        with pytest.raises(ValueError, match="At least one of"):
            search_feeds()

    @patch("netweave.io.transitland._request")
    def test_limit_respected(self, mock_request, sample_feed_response):
        # Return 2 feeds but limit to 1
        mock_request.return_value = sample_feed_response
        df = search_feeds(search="test", limit=1)
        assert len(df) == 1


# ---------------------------------------------------------------------------
# download_feed
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("mock_api_key")
class TestDownloadFeed:
    @patch("netweave.io.transitland.requests.get")
    @patch("netweave.io.transitland._load_feed_from_buffer")
    def test_in_memory(
        self,
        mock_load,
        mock_get,
        mock_gtfs_zip_bytes,
        minimal_gtfs_feed,
    ):
        mock_response = MagicMock()
        mock_response.headers = {"content-length": str(len(mock_gtfs_zip_bytes))}
        mock_response.iter_content.return_value = [mock_gtfs_zip_bytes]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        mock_load.return_value = minimal_gtfs_feed

        result = download_feed("f-test")
        assert isinstance(result, GTFSFeed)
        mock_get.assert_called_once()

    @patch("netweave.io.transitland.requests.get")
    @patch("netweave.io.transitland._load_feed_from_buffer")
    def test_with_output_dir(
        self,
        mock_load,
        mock_get,
        mock_gtfs_zip_bytes,
        minimal_gtfs_feed,
        tmp_path,
    ):
        mock_response = MagicMock()
        mock_response.headers = {"content-length": str(len(mock_gtfs_zip_bytes))}
        mock_response.iter_content.return_value = [mock_gtfs_zip_bytes]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        mock_load.return_value = minimal_gtfs_feed

        output_dir = tmp_path / "feeds"
        result = download_feed("f-test", output_dir=output_dir)
        assert isinstance(result, tuple)
        feed, path = result
        assert isinstance(feed, GTFSFeed)
        assert path == output_dir / "f-test.zip"
        assert path.exists()

    @patch("netweave.io.transitland.requests.get")
    def test_download_failure(self, mock_get):
        from requests.exceptions import HTTPError

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        with pytest.raises(TransitlandAPIError, match="Failed to download"):
            download_feed("f-test")


# ---------------------------------------------------------------------------
# fetch_feeds
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("mock_api_key")
class TestFetchFeeds:
    @patch("netweave.io.transitland.search_feeds")
    @patch("netweave.io.transitland.download_feed")
    def test_merge_true(
        self,
        mock_download,
        mock_search,
        minimal_gtfs_feed,
    ):
        mock_search.return_value = pd.DataFrame({
            "feed_key": ["f-1", "f-2"],
            "onestop_id": ["f-1", "f-2"],
            "name": ["Feed 1", "Feed 2"],
            "spec": ["gtfs", "gtfs"],
            "static_current": ["url1", "url2"],
            "license_redistribution": ["yes", "yes"],
        })
        mock_download.side_effect = [
            minimal_gtfs_feed,
            minimal_gtfs_feed,
        ]

        result = fetch_feeds(search="test", merge=True)
        assert isinstance(result, GTFSFeed)
        # Merged feed should have double the trips
        assert len(result.trips) == len(minimal_gtfs_feed.trips) * 2

    @patch("netweave.io.transitland.search_feeds")
    @patch("netweave.io.transitland.download_feed")
    def test_merge_false(
        self,
        mock_download,
        mock_search,
        minimal_gtfs_feed,
    ):
        mock_search.return_value = pd.DataFrame({
            "feed_key": ["f-1"],
            "onestop_id": ["f-1"],
            "name": ["Feed 1"],
            "spec": ["gtfs"],
            "static_current": ["url1"],
            "license_redistribution": ["yes"],
        })
        mock_download.return_value = minimal_gtfs_feed

        result = fetch_feeds(search="test", merge=False)
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], GTFSFeed)

    @patch("netweave.io.transitland.search_feeds")
    @patch("netweave.io.transitland.download_feed")
    def test_skip_no_redistribution(
        self,
        mock_download,
        mock_search,
        minimal_gtfs_feed,
    ):
        mock_search.return_value = pd.DataFrame({
            "feed_key": ["f-1", "f-2"],
            "onestop_id": ["f-1", "f-2"],
            "name": ["Feed 1", "Feed 2"],
            "spec": ["gtfs", "gtfs"],
            "static_current": ["url1", "url2"],
            "license_redistribution": ["yes", "no"],
        })
        mock_download.return_value = minimal_gtfs_feed

        result = fetch_feeds(search="test", merge=True)
        assert isinstance(result, GTFSFeed)
        # Only one feed should be downloaded (the other skipped)
        assert mock_download.call_count == 1

    @patch("netweave.io.transitland.search_feeds")
    @patch("netweave.io.transitland.download_feed")
    def test_all_failed_raises(
        self,
        mock_download,
        mock_search,
    ):
        mock_search.return_value = pd.DataFrame({
            "feed_key": ["f-1"],
            "onestop_id": ["f-1"],
            "name": ["Feed 1"],
            "spec": ["gtfs"],
            "static_current": ["url1"],
            "license_redistribution": ["yes"],
        })
        mock_download.side_effect = TransitlandAPIError("Download failed")

        with pytest.raises(NoFeedsFoundError, match="No feeds could be downloaded"):
            fetch_feeds(search="test")


# ---------------------------------------------------------------------------
# transit_network_from_transitland
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("mock_api_key")
class TestTransitNetworkFromTransitland:
    @patch("netweave.io.transitland.fetch_feeds")
    @patch("netweave.io.transitland.create_transit_network")
    def test_basic(
        self,
        mock_create,
        mock_fetch,
        minimal_gtfs_feed,
    ):
        mock_fetch.return_value = minimal_gtfs_feed
        mock_network = TransitNetwork(
            edges=pd.DataFrame({"from": [1], "to": [2], "weight": [5.0]}),
            nodes=pd.DataFrame({"node_id": [1], "x": [0.0], "y": [0.0]}),
        )
        mock_create.return_value = mock_network

        result = transit_network_from_transitland(
            search="test",
            day="monday",
            timerange=("07:00:00", "10:00:00"),
        )
        assert isinstance(result, TransitNetwork)
        mock_fetch.assert_called_once()
        mock_create.assert_called_once_with(
            minimal_gtfs_feed,
            day="monday",
            timerange=("07:00:00", "10:00:00"),
        )


# ---------------------------------------------------------------------------
# Polygon input (GeoDataFrame / shapely)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("mock_api_key")
class TestPolygonInput:
    @patch("netweave.io.transitland._request")
    def test_geodataframe(self, mock_request, sample_feed_response):
        gpd = pytest.importorskip("geopandas")
        from shapely.geometry import box

        stops_response = {
            "stops": [
                {"feed_version": {"feed": {"onestop_id": "f-sf~bay~area~rg"}}},
                {"feed_version": {"feed": {"onestop_id": "f-sf~muni"}}},
            ],
            "meta": {"after": None},
        }
        mock_request.side_effect = [stops_response, sample_feed_response]
        gdf = gpd.GeoDataFrame(
            geometry=[box(-122.5, 37.7, -122.4, 37.8)],
        )
        df = search_feeds(polygon=gdf)
        assert len(df) == 2
        assert mock_request.call_count == 2
        # First call should be to /stops
        assert "stops" in mock_request.call_args_list[0][0][0]
        # Second call should be to /feeds
        _, params, _ = mock_request.call_args_list[1][0]
        assert params["bbox"] == "-122.5,37.7,-122.4,37.8"

    @patch("netweave.io.transitland._request")
    def test_shapely_polygon(self, mock_request, sample_feed_response):
        from shapely.geometry import box

        stops_response = {
            "stops": [
                {"feed_version": {"feed": {"onestop_id": "f-sf~bay~area~rg"}}},
                {"feed_version": {"feed": {"onestop_id": "f-sf~muni"}}},
            ],
            "meta": {"after": None},
        }
        mock_request.side_effect = [stops_response, sample_feed_response]
        polygon = box(-122.5, 37.7, -122.4, 37.8)
        df = search_feeds(polygon=polygon)
        assert len(df) == 2
        assert mock_request.call_count == 2
        # First call should be to /stops
        assert "stops" in mock_request.call_args_list[0][0][0]
        # Second call should be to /feeds
        _, params, _ = mock_request.call_args_list[1][0]
        assert params["bbox"] == "-122.5,37.7,-122.4,37.8"
