"""Tests for GTFS feed loading and validation."""


import pandas as pd
import pytest

from netweave.exceptions import InvalidGTFS
from netweave.gtfs.feed import GTFSFeed, load_feed


class TestGTFSFeed:
    def test_empty_feed_validation_fails(self) -> None:
        feed = GTFSFeed()
        with pytest.raises(InvalidGTFS):
            feed.validate()

    def test_minimal_feed_validation_passes(self, minimal_gtfs_feed: GTFSFeed) -> None:
        minimal_gtfs_feed.validate()
        assert minimal_gtfs_feed.has_calendar
        assert not minimal_gtfs_feed.has_calendar_dates
        assert not minimal_gtfs_feed.has_frequencies

    def test_merge_feeds(self, minimal_gtfs_feed: GTFSFeed) -> None:
        other = minimal_gtfs_feed
        merged = minimal_gtfs_feed.merge(other)
        assert len(merged.trips) == len(minimal_gtfs_feed.trips) * 2
        assert len(merged.stop_times) == len(minimal_gtfs_feed.stop_times) * 2

    def test_missing_required_file(self, minimal_gtfs_feed: GTFSFeed) -> None:
        minimal_gtfs_feed.routes = pd.DataFrame()
        with pytest.raises(InvalidGTFS):
            minimal_gtfs_feed.validate()

    def test_missing_column(self, minimal_gtfs_feed: GTFSFeed) -> None:
        minimal_gtfs_feed.stops = minimal_gtfs_feed.stops.drop(columns=["stop_lat"])
        with pytest.raises(InvalidGTFS):
            minimal_gtfs_feed.validate()


class TestLoadFeed:
    def test_load_from_nonexistent_path(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_feed("/nonexistent/path.zip")

    def test_load_from_invalid_path(self) -> None:
        with pytest.raises((ValueError, FileNotFoundError)):
            load_feed("/nonexistent/path.txt")
