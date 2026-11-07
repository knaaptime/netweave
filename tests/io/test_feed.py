"""Tests for reading GTFS feeds from disk."""

import zipfile

import pandas as pd
import pytest

from netweave.exceptions import InvalidGTFS
from netweave.io.gtfs import GTFSFeed, load_feed


def _zip_folder(folder, destination, inner=""):
    with zipfile.ZipFile(destination, "w") as archive:
        for path in folder.iterdir():
            archive.write(path, f"{inner}{path.name}")
    return destination


class TestLoadFeed:
    def test_ordering_columns_are_numbers(self, line_tables, write_feed) -> None:
        feed = load_feed(write_feed(line_tables()))
        ordered = feed.stop_times[feed.stop_times["trip_id"] == "1"].sort_values("stop_sequence")
        assert ordered["stop_sequence"].tolist() == list(range(1, 13))
        assert feed.stops["stop_lat"].iloc[1] == pytest.approx(37.001)
        assert feed.stops["stop_lon"].iloc[1] == pytest.approx(-122.001)

    def test_numeric_looking_ids_stay_text(self, line_tables, write_feed) -> None:
        feed = load_feed(write_feed(line_tables()))
        assert feed.stops["stop_id"].iloc[0] == "1000"
        assert feed.stop_times["stop_id"].iloc[0] == "1000"
        assert feed.trips["trip_id"].iloc[0] == "1"

    def test_ids_given_as_integers_become_text(self) -> None:
        feed = GTFSFeed(
            stops=pd.DataFrame({"stop_id": [101], "stop_lat": [37.0], "stop_lon": [-122.0]})
        )
        assert feed.stops["stop_id"].iloc[0] == "101"

    def test_reads_a_zip(self, line_tables, write_feed, tmp_path) -> None:
        archive = _zip_folder(write_feed(line_tables()), tmp_path / "feed.zip")
        feed = load_feed(archive)
        assert len(feed.stop_times) == 36
        assert feed.name == "feed"

    def test_reads_a_zip_with_an_inner_folder(self, line_tables, write_feed, tmp_path) -> None:
        archive = _zip_folder(write_feed(line_tables()), tmp_path / "nested.zip", inner="gtfs/")
        assert len(load_feed(archive).stops) == 12

    def test_zero_byte_optional_file_counts_as_absent(self, line_tables, write_feed) -> None:
        folder = write_feed(line_tables())
        (folder / "frequencies.txt").write_bytes(b"")
        assert load_feed(folder).frequencies.empty

    def test_missing_path_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_feed("/nonexistent/path.zip")


class TestValidate:
    def test_real_format_feed_passes(self, line_tables, write_feed) -> None:
        load_feed(write_feed(line_tables())).validate()

    def test_empty_feed_fails(self) -> None:
        with pytest.raises(InvalidGTFS):
            GTFSFeed().validate()

    def test_missing_required_table_fails(self, line_tables, write_feed) -> None:
        tables = line_tables()
        del tables["routes"]
        with pytest.raises(InvalidGTFS, match="routes"):
            load_feed(write_feed(tables)).validate()

    def test_missing_required_column_fails(self, line_tables, write_feed) -> None:
        tables = line_tables()
        del tables["stops"]["stop_lat"]
        with pytest.raises(InvalidGTFS, match="stop_lat"):
            load_feed(write_feed(tables)).validate()

    def test_single_agency_may_omit_agency_id(self, line_tables, write_feed) -> None:
        tables = line_tables()
        del tables["agency"]["agency_id"]
        del tables["routes"]["agency_id"]
        load_feed(write_feed(tables)).validate()

    def test_several_agencies_require_agency_id(self, line_tables, write_feed) -> None:
        tables = line_tables()
        tables["agency"] = {"agency_name": ["One", "Two"]}
        del tables["routes"]["agency_id"]
        with pytest.raises(InvalidGTFS, match="agency_id"):
            load_feed(write_feed(tables)).validate()

    def test_unreadable_stop_sequence_fails(self, line_tables, write_feed) -> None:
        tables = line_tables()
        tables["stop_times"]["stop_sequence"][0] = "first"
        with pytest.raises(InvalidGTFS, match="stop_sequence"):
            load_feed(write_feed(tables)).validate()

    def test_orphan_stop_warns(self, line_tables, write_feed) -> None:
        tables = line_tables()
        tables["stop_times"]["stop_id"][0] = "9999"
        with pytest.warns(UserWarning, match="stop_id"):
            load_feed(write_feed(tables)).validate()
