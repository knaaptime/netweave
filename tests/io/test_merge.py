"""Tests for merging GTFS feeds."""

import pandas as pd
import pytest

from netweave.io.gtfs import GTFSFeed, load_feed, merge_feeds


@pytest.fixture
def two_feeds(line_tables, write_feed):
    """Two feeds whose stop, route and trip IDs collide completely."""
    first = load_feed(write_feed(line_tables(n_stops=3), name="first"))
    second = load_feed(write_feed(line_tables(n_stops=3), name="second"))
    first.onestop_id = "f-a"
    second.onestop_id = "f-b"
    return first, second


class TestPrefixes:
    def test_every_feed_gets_a_prefix_including_the_first(self, two_feeds) -> None:
        merged = merge_feeds(two_feeds)
        assert merged.stops["stop_id"].tolist() == [
            "f-a_1000",
            "f-a_1001",
            "f-a_1002",
            "f-b_1000",
            "f-b_1001",
            "f-b_1002",
        ]

    def test_prefix_falls_back_from_onestop_id_to_feed_key_to_position(
        self, line_tables, write_feed
    ) -> None:
        with_onestop = load_feed(write_feed(line_tables(n_stops=2), name="a"))
        with_onestop.onestop_id, with_onestop.feed_key = "f-a", "11"
        with_key = load_feed(write_feed(line_tables(n_stops=2), name="b"))
        with_key.feed_key = "22"
        with_nothing = load_feed(write_feed(line_tables(n_stops=2), name="c"))
        merged = merge_feeds([with_onestop, with_key, with_nothing])
        assert [source["prefix"] for source in merged.sources] == ["f-a", "22", "feed_2"]

    def test_name_is_not_used_as_a_prefix(self, line_tables, write_feed) -> None:
        feed = load_feed(write_feed(line_tables(n_stops=2), name="metro"))
        assert merge_feeds([feed]).sources[0]["prefix"] == "feed_0"

    def test_feeds_sharing_an_identity_still_get_distinct_prefixes(self, two_feeds) -> None:
        first, second = two_feeds
        second.onestop_id = first.onestop_id
        merged = merge_feeds([first, second])
        prefixes = [source["prefix"] for source in merged.sources]
        assert prefixes == ["f-a", "f-a_2"]
        assert merged.stops["stop_id"].is_unique

    def test_explicit_prefixes_are_used(self, two_feeds) -> None:
        merged = merge_feeds(two_feeds, prefixes=["north", "south"])
        assert merged.routes["route_id"].tolist() == ["north_10", "south_10"]

    def test_duplicate_explicit_prefixes_are_refused(self, two_feeds) -> None:
        with pytest.raises(ValueError, match="distinct"):
            merge_feeds(two_feeds, prefixes=["same", "same"])

    def test_wrong_number_of_prefixes_is_refused(self, two_feeds) -> None:
        with pytest.raises(ValueError, match="one prefix"):
            merge_feeds(two_feeds, prefixes=["only"])


class TestMergedTables:
    def test_foreign_keys_stay_linked(self, two_feeds) -> None:
        merged = merge_feeds(two_feeds)
        assert set(merged.stop_times["stop_id"]) == set(merged.stops["stop_id"])
        assert set(merged.stop_times["trip_id"]) == set(merged.trips["trip_id"])
        assert set(merged.trips["route_id"]) == set(merged.routes["route_id"])
        assert set(merged.trips["service_id"]) == set(merged.calendar["service_id"])
        assert set(merged.routes["agency_id"]) == set(merged.agency["agency_id"])

    def test_tables_record_their_feed(self, two_feeds) -> None:
        merged = merge_feeds(two_feeds)
        for table in (merged.stops, merged.routes, merged.trips, merged.calendar):
            assert sorted(table["feed"].unique()) == ["f-a", "f-b"]

    def test_empty_ids_stay_empty(self, line_tables, write_feed) -> None:
        tables = line_tables(n_stops=2)
        tables["stops"]["zone_id"] = ["Z1", ""]
        tables["stops"]["parent_station"] = ["", "1000"]
        merged = merge_feeds([load_feed(write_feed(tables))], prefixes=["p"])
        assert merged.stops["zone_id"].iloc[0] == "p_Z1"
        assert pd.isna(merged.stops["zone_id"].iloc[1])
        assert pd.isna(merged.stops["parent_station"].iloc[0])
        assert merged.stops["parent_station"].iloc[1] == "p_1000"

    def test_transfer_references_are_prefixed(self, line_tables, write_feed) -> None:
        tables = line_tables(n_stops=2)
        tables["transfers"] = {
            "from_stop_id": ["1000"],
            "to_stop_id": ["1001"],
            "transfer_type": ["2"],
        }
        merged = merge_feeds([load_feed(write_feed(tables))], prefixes=["p"])
        assert merged.transfers["from_stop_id"].iloc[0] == "p_1000"
        assert merged.transfers["to_stop_id"].iloc[0] == "p_1001"
        assert merged.transfers["transfer_type"].iloc[0] == "2"

    def test_sources_record_where_each_feed_came_from(self, two_feeds) -> None:
        first, second = two_feeds
        first.name, first.feed_key = "Agency A", "7"
        source = merge_feeds([first, second]).sources[0]
        assert source == {"prefix": "f-a", "onestop_id": "f-a", "feed_key": "7", "name": "Agency A"}

    def test_inputs_are_not_changed(self, two_feeds) -> None:
        first, _ = two_feeds
        merge_feeds(two_feeds)
        assert first.stops["stop_id"].iloc[0] == "1000"
        assert "feed" not in first.stops.columns


class TestRepeatedMerging:
    def test_merging_a_merged_feed_alone_returns_it(self, two_feeds) -> None:
        merged = merge_feeds(two_feeds)
        assert merge_feeds([merged]) is merged

    def test_a_merged_feed_keeps_its_prefixes_when_merged_again(
        self, two_feeds, line_tables, write_feed
    ) -> None:
        merged = merge_feeds(two_feeds)
        third = load_feed(write_feed(line_tables(n_stops=3), name="third"))
        third.onestop_id = "f-a"
        again = merge_feeds([merged, third])
        assert [source["prefix"] for source in again.sources] == ["f-a", "f-b", "f-a_2"]
        assert again.stops["stop_id"].is_unique

    def test_missing_feed_records_carry_through(self, two_feeds) -> None:
        first, second = two_feeds
        first.missing = [{"feed": "f-x", "reason": "licence"}]
        assert merge_feeds([first, second]).missing == [{"feed": "f-x", "reason": "licence"}]

    def test_no_feeds_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            merge_feeds([])

    def test_merged_empty_optional_tables_stay_empty(self, two_feeds) -> None:
        merged = merge_feeds(two_feeds)
        assert isinstance(merged, GTFSFeed)
        assert merged.shapes.empty
