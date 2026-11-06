"""Tests for the Transitland client, with only HTTP replaced."""

import io
import time
import warnings
import zipfile

import geopandas as gpd
import pytest
import requests
from shapely.geometry import box

from netweave.exceptions import NoFeedsFoundError, TransitlandAPIError
from netweave.io.gtfs import GTFSFeed
from netweave.io.transitland import fetch_feeds, search_feeds

KEY = "secret-test-key"


def source_url(onestop_id):
    return f"https://agency.example/{onestop_id}.zip"


def feed_record(onestop_id, name=None, key=1, redistribution="yes", has_source=True):
    return {
        "id": key,
        "onestop_id": onestop_id,
        "name": name,
        "spec": "gtfs",
        "urls": {"static_current": source_url(onestop_id)} if has_source else {},
        "license": {"redistribution_allowed": redistribution},
        "feed_state": {},
    }


def stop_in(onestop_id):
    return {"feed_version": {"feed": {"onestop_id": onestop_id}}}


class FakeResponse:
    def __init__(self, url, params, payload=None, content=b"", status=200):
        self.url = f"{url}?apikey={(params or {}).get('apikey')}"
        self.payload, self.content, self.status_code = payload, content, status
        self.headers = {"content-length": str(len(content))}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} Error for url: {self.url}")

    def iter_content(self, chunk_size):  # noqa: ARG002
        yield self.content


class FakeTransitland:
    """Stand in for the three Transitland endpoints the client uses, and agency servers."""

    def __init__(
        self, feeds=None, stop_pages=None, feed_pages=None, downloads=None, slow=(), sources=None
    ):
        self.feed_pages = feed_pages or {None: (feeds or [], None)}
        self.stop_pages = stop_pages or {None: ([], None)}
        self.downloads = downloads or {}
        self.sources = sources or {}
        self.slow = slow
        self.calls = []

    def get(self, url, params=None, **_):
        params = params or {}
        self.calls.append((url, dict(params)))
        if url.startswith("https://agency.example/"):
            source = self.sources.get(url, 404)
            if isinstance(source, int):
                return FakeResponse(url, params, status=source)
            return FakeResponse(url, params, content=source)
        if url.endswith("/download_latest_feed_version"):
            onestop_id = url.split("/feeds/")[1].split("/")[0]
            if onestop_id in self.slow:
                time.sleep(0.05)
            download = self.downloads.get(onestop_id, 404)
            if isinstance(download, int):
                return FakeResponse(url, params, status=download)
            return FakeResponse(url, params, content=download)
        pages, field = (
            (self.stop_pages, "stops") if url.endswith("/stops") else (self.feed_pages, "feeds")
        )
        records, after = pages.get(params.get("after"), ([], None))
        return FakeResponse(url, params, payload={field: records, "meta": {"after": after}})

    def params_for(self, suffix):
        return [params for url, params in self.calls if url.endswith(suffix)]


@pytest.fixture
def install(monkeypatch):
    """Replace requests.get with a fake Transitland, and disable retry delays."""

    def _install(api):
        monkeypatch.setattr("netweave.io.transitland.requests.get", api.get)
        monkeypatch.setattr("netweave.io.transitland._RETRY_BACKOFF", 0.0)
        return api

    return _install


@pytest.fixture
def gtfs_zip(line_tables, write_feed):
    """Return the bytes of a valid GTFS zip."""
    counter = iter(range(100))

    def _zip(**kwargs):
        folder = write_feed(line_tables(n_stops=2, **kwargs), name=f"zip{next(counter)}")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for path in folder.iterdir():
                archive.write(path, path.name)
        return buffer.getvalue()

    return _zip


class TestSearchFeeds:
    def test_area_search_keeps_only_feeds_with_stops_in_the_area(self, install) -> None:
        api = install(
            FakeTransitland(
                feeds=[feed_record("f-near", "Near"), feed_record("f-far", "Far")],
                stop_pages={None: ([stop_in("f-near")], None)},
            )
        )
        table = search_feeds(bbox=(-122.5, 37.7, -122.3, 37.9), api_key=KEY)
        assert table["onestop_id"].tolist() == ["f-near"]
        assert api.params_for("/stops")[0]["bbox"] == "-122.5,37.7,-122.3,37.9"

    def test_area_search_can_skip_the_stop_check(self, install) -> None:
        api = install(FakeTransitland(feeds=[feed_record("f-a")]))
        table = search_feeds(bbox=(0, 0, 1, 1), api_key=KEY, verify_stops=False)
        assert table["onestop_id"].tolist() == ["f-a"]
        assert api.params_for("/stops") == []

    def test_text_search_needs_no_stop_check(self, install) -> None:
        api = install(FakeTransitland(feeds=[feed_record("f-a")]))
        search_feeds(search="caltrain", api_key=KEY)
        assert api.params_for("/feeds")[0]["search"] == "caltrain"
        assert api.params_for("/stops") == []

    def test_follows_pagination(self, install) -> None:
        install(
            FakeTransitland(
                feed_pages={
                    None: ([feed_record("f-1")], 99),
                    99: ([feed_record("f-2")], None),
                }
            )
        )
        assert search_feeds(search="x", api_key=KEY)["onestop_id"].tolist() == ["f-1", "f-2"]

    def test_respects_the_limit(self, install) -> None:
        install(FakeTransitland(feeds=[feed_record(f"f-{i}") for i in range(5)]))
        assert len(search_feeds(search="x", limit=2, api_key=KEY)) == 2

    def test_no_matches_raises(self, install) -> None:
        install(FakeTransitland())
        with pytest.raises(NoFeedsFoundError):
            search_feeds(search="nothing", api_key=KEY)

    def test_no_stops_in_the_area_raises(self, install) -> None:
        install(FakeTransitland(feeds=[feed_record("f-far")]))
        with pytest.raises(NoFeedsFoundError, match="stops"):
            search_feeds(bbox=(0, 0, 1, 1), api_key=KEY)

    def test_no_filter_is_refused(self) -> None:
        with pytest.raises(ValueError, match="bbox"):
            search_feeds(api_key=KEY)

    def test_key_comes_from_the_environment(self, install, monkeypatch) -> None:
        monkeypatch.setenv("TRANSITLAND_API_KEY", "from-env")
        api = install(FakeTransitland(feeds=[feed_record("f-a")]))
        search_feeds(search="x")
        assert api.params_for("/feeds")[0]["apikey"] == "from-env"

    def test_explicit_key_overrides_the_environment(self, install, monkeypatch) -> None:
        monkeypatch.setenv("TRANSITLAND_API_KEY", "from-env")
        api = install(FakeTransitland(feeds=[feed_record("f-a")]))
        search_feeds(search="x", api_key=KEY)
        assert api.params_for("/feeds")[0]["apikey"] == KEY

    def test_missing_key_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("TRANSITLAND_API_KEY", raising=False)
        with pytest.raises(TransitlandAPIError, match="API key"):
            search_feeds(search="x")

    def test_projected_polygon_is_queried_in_lon_lat(self, install) -> None:
        api = install(
            FakeTransitland(feeds=[feed_record("f-a")], stop_pages={None: ([stop_in("f-a")], None)})
        )
        area = gpd.GeoDataFrame(geometry=[box(-122.5, 37.7, -122.3, 37.9)], crs=4326).to_crs(3857)
        search_feeds(polygon=area, api_key=KEY)
        west, south, east, north = map(float, api.params_for("/stops")[0]["bbox"].split(","))
        assert west == pytest.approx(-122.5)
        assert south == pytest.approx(37.7)
        assert east == pytest.approx(-122.3)
        assert north == pytest.approx(37.9)

    def test_shapely_polygon_is_accepted(self, install) -> None:
        api = install(
            FakeTransitland(feeds=[feed_record("f-a")], stop_pages={None: ([stop_in("f-a")], None)})
        )
        search_feeds(polygon=box(0, 1, 2, 3), api_key=KEY)
        assert api.params_for("/stops")[0]["bbox"] == "0.0,1.0,2.0,3.0"

    def test_warns_when_the_stop_check_reaches_its_limit(self, install) -> None:
        endless = {page: ([stop_in("f-a")], page + 1) for page in range(1, 60)}
        endless[None] = ([stop_in("f-a")], 1)
        install(FakeTransitland(feeds=[feed_record("f-a")], stop_pages=endless))
        with pytest.warns(UserWarning, match="incomplete"):
            search_feeds(bbox=(0, 0, 1, 1), api_key=KEY)

    def test_request_failure_does_not_reveal_the_key(self, monkeypatch) -> None:
        def fail(url, params=None, **_):
            return FakeResponse(url, params, status=500)

        monkeypatch.setattr("netweave.io.transitland.requests.get", fail)
        monkeypatch.setattr("netweave.io.transitland._RETRY_BACKOFF", 0.0)
        with pytest.raises(TransitlandAPIError) as caught:
            search_feeds(search="x", api_key=KEY)
        assert KEY not in str(caught.value)


class TestFetchFeeds:
    def test_merges_by_default_with_stable_prefixes(self, install, gtfs_zip) -> None:
        install(
            FakeTransitland(
                feeds=[feed_record("f-b", "Bee", key=2), feed_record("f-a", "Ay", key=1)],
                downloads={"f-a": gtfs_zip(), "f-b": gtfs_zip()},
                slow={"f-b"},
            )
        )
        feed = fetch_feeds(search="x", api_key=KEY, max_workers=2)
        assert isinstance(feed, GTFSFeed)
        assert feed.sources == [
            {"prefix": "f-b", "onestop_id": "f-b", "feed_key": "2", "name": "Bee"},
            {"prefix": "f-a", "onestop_id": "f-a", "feed_key": "1", "name": "Ay"},
        ]
        assert feed.stops["stop_id"].tolist()[0] == "f-b_1000"

    def test_can_return_separate_feeds_in_search_order(self, install, gtfs_zip) -> None:
        install(
            FakeTransitland(
                feeds=[feed_record("f-b"), feed_record("f-a")],
                downloads={"f-a": gtfs_zip(), "f-b": gtfs_zip()},
                slow={"f-b"},
            )
        )
        feeds = fetch_feeds(search="x", api_key=KEY, merge=False, max_workers=2)
        assert [feed.onestop_id for feed in feeds] == ["f-b", "f-a"]

    def test_corrupt_zip_is_left_out_with_a_warning(self, install, gtfs_zip) -> None:
        install(
            FakeTransitland(
                feeds=[feed_record("f-bad"), feed_record("f-good")],
                downloads={"f-bad": b"not a zip", "f-good": gtfs_zip()},
            )
        )
        with pytest.warns(UserWarning, match="f-bad"):
            feed = fetch_feeds(search="x", api_key=KEY)
        assert [source["prefix"] for source in feed.sources] == ["f-good"]
        assert [record["feed"] for record in feed.missing] == ["f-bad"]

    def test_invalid_feed_is_left_out_with_a_warning(self, install, gtfs_zip) -> None:
        empty = io.BytesIO()
        with zipfile.ZipFile(empty, "w") as archive:
            archive.writestr("stops.txt", "stop_id,stop_lat,stop_lon\n1,0,0\n")
        install(
            FakeTransitland(
                feeds=[feed_record("f-thin"), feed_record("f-good")],
                downloads={"f-thin": empty.getvalue(), "f-good": gtfs_zip()},
            )
        )
        with pytest.warns(UserWarning, match="f-thin.*agency"):
            feed = fetch_feeds(search="x", api_key=KEY)
        assert "agency" in feed.missing[0]["reason"]

    def test_failed_download_warns_without_revealing_the_key(self, install, gtfs_zip) -> None:
        install(
            FakeTransitland(
                feeds=[feed_record("f-gone"), feed_record("f-good")],
                downloads={"f-gone": 503, "f-good": gtfs_zip()},
            )
        )
        with pytest.warns(UserWarning, match="f-gone") as caught:
            feed = fetch_feeds(search="x", api_key=KEY)
        assert KEY not in str(caught[0].message)
        assert KEY not in feed.missing[0]["reason"]

    def test_a_restrictive_license_does_not_exclude_a_feed(self, install, gtfs_zip) -> None:
        api = install(
            FakeTransitland(
                feeds=[feed_record("f-closed", redistribution="no")],
                downloads={"f-closed": gtfs_zip()},
            )
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            feed = fetch_feeds(search="x", api_key=KEY)
        assert [source["prefix"] for source in feed.sources] == ["f-closed"]
        assert feed.missing == []
        assert api.params_for(".zip") == []

    def test_a_feed_transitland_refuses_comes_from_its_source(self, install, gtfs_zip) -> None:
        install(
            FakeTransitland(
                feeds=[feed_record("f-closed", redistribution="no"), feed_record("f-open")],
                downloads={"f-closed": 401, "f-open": gtfs_zip()},
                sources={source_url("f-closed"): gtfs_zip()},
            )
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            feed = fetch_feeds(search="x", api_key=KEY)
        assert [source["prefix"] for source in feed.sources] == ["f-closed", "f-open"]
        assert feed.stops["stop_id"].tolist()[0] == "f-closed_1000"
        assert feed.missing == []

    def test_the_api_key_is_not_sent_to_the_source(self, install, gtfs_zip) -> None:
        api = install(
            FakeTransitland(
                feeds=[feed_record("f-closed")],
                downloads={"f-closed": 401},
                sources={source_url("f-closed"): gtfs_zip()},
            )
        )
        fetch_feeds(search="x", api_key=KEY)
        requested = [(url, params) for url, params in api.calls if "agency.example" in url]
        assert requested == [(source_url("f-closed"), {})]

    def test_a_non_zip_from_transitland_comes_from_the_source(self, install, gtfs_zip) -> None:
        install(
            FakeTransitland(
                feeds=[feed_record("f-a")],
                downloads={"f-a": b"<html>not allowed</html>"},
                sources={source_url("f-a"): gtfs_zip()},
            )
        )
        assert [source["prefix"] for source in fetch_feeds(search="x", api_key=KEY).sources] == [
            "f-a"
        ]

    def test_saves_a_download_from_the_source(self, install, gtfs_zip, tmp_path) -> None:
        archive = gtfs_zip()
        install(
            FakeTransitland(
                feeds=[feed_record("f-a")],
                downloads={"f-a": 401},
                sources={source_url("f-a"): archive},
            )
        )
        fetch_feeds(search="x", api_key=KEY, output_dir=tmp_path / "zips")
        assert (tmp_path / "zips" / "f-a.zip").read_bytes() == archive

    def test_when_both_refuse_the_warning_gives_both_reasons(self, install, gtfs_zip) -> None:
        install(
            FakeTransitland(
                feeds=[feed_record("f-gone"), feed_record("f-good")],
                downloads={"f-gone": 401, "f-good": gtfs_zip()},
                sources={source_url("f-gone"): 503},
            )
        )
        with pytest.warns(UserWarning, match="f-gone") as caught:
            feed = fetch_feeds(search="x", api_key=KEY)
        reason = feed.missing[0]["reason"]
        assert "401" in reason
        assert "503" in reason
        assert KEY not in reason
        assert KEY not in str(caught[0].message)

    def test_a_feed_without_a_source_gives_transitlands_reason(self, install, gtfs_zip) -> None:
        install(
            FakeTransitland(
                feeds=[feed_record("f-gone", has_source=False), feed_record("f-good")],
                downloads={"f-gone": 401, "f-good": gtfs_zip()},
            )
        )
        with pytest.warns(UserWarning, match="f-gone.*401"):
            feed = fetch_feeds(search="x", api_key=KEY)
        assert [record["feed"] for record in feed.missing] == ["f-gone"]

    def test_a_bad_archive_from_the_source_is_left_out(self, install, gtfs_zip) -> None:
        install(
            FakeTransitland(
                feeds=[feed_record("f-bad"), feed_record("f-good")],
                downloads={"f-bad": 401, "f-good": gtfs_zip()},
                sources={source_url("f-bad"): b"<html>sign in</html>"},
            )
        )
        with pytest.warns(UserWarning, match="f-bad"):
            feed = fetch_feeds(search="x", api_key=KEY)
        assert [source["prefix"] for source in feed.sources] == ["f-good"]

    def test_skipping_by_license_is_no_longer_an_option(self, install) -> None:
        install(FakeTransitland())
        with pytest.raises(TypeError, match="skip_no_redistribution"):
            fetch_feeds(search="x", api_key=KEY, skip_no_redistribution=True)

    def test_raises_with_reasons_when_no_feed_succeeds(self, install) -> None:
        install(FakeTransitland(feeds=[feed_record("f-bad")], downloads={"f-bad": b"not a zip"}))
        with pytest.warns(UserWarning), pytest.raises(NoFeedsFoundError, match="f-bad"):
            fetch_feeds(search="x", api_key=KEY)

    def test_saves_downloads_when_asked(self, install, gtfs_zip, tmp_path) -> None:
        install(FakeTransitland(feeds=[feed_record("f-a")], downloads={"f-a": gtfs_zip()}))
        fetch_feeds(search="x", api_key=KEY, output_dir=tmp_path / "zips")
        assert (tmp_path / "zips" / "f-a.zip").exists()
