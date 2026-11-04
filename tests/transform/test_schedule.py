"""Tests for GTFS schedule processing."""


import pandas as pd
import pytest

from netweave.exceptions import TimeFormatError
from netweave.transform.schedule import (
    add_unique_ids,
    interpolate_stop_times,
    seconds_to_time,
    select_by_time_range,
    timetoseconds,
)


class TestTimeToSeconds:
    def test_basic_conversion(self) -> None:
        s = pd.Series(["00:00:00", "01:00:00", "12:34:56"])
        result = timetoseconds(s)
        assert result.iloc[0] == 0
        assert result.iloc[1] == 3600
        assert result.iloc[2] == 12 * 3600 + 34 * 60 + 56

    def test_invalid_format_raises(self) -> None:
        s = pd.Series(["not_a_time"])
        with pytest.raises(TimeFormatError):
            timetoseconds(s)


class TestSecondsToTime:
    def test_basic_conversion(self) -> None:
        s = pd.Series([0, 3600, 12 * 3600 + 34 * 60 + 56])
        result = seconds_to_time(s)
        assert result.iloc[0] == "00:00:00"
        assert result.iloc[1] == "01:00:00"
        assert result.iloc[2] == "12:34:56"


class TestSelectByTimeRange:
    def test_select_within_range(self) -> None:
        df = pd.DataFrame({
            "trip_id": ["T1", "T1", "T1"],
            "departure_time": ["07:00:00", "08:00:00", "09:00:00"],
        })
        result = select_by_time_range(df, "07:30:00", "08:30:00")
        assert len(result) == 1
        assert result.iloc[0]["departure_time"] == "08:00:00"

    def test_select_with_pad(self) -> None:
        df = pd.DataFrame({
            "trip_id": ["T1", "T1", "T1"],
            "departure_time": ["07:00:00", "08:00:00", "09:00:00"],
        })
        result = select_by_time_range(df, "07:30:00", "08:30:00", pad="01:00:00")
        assert len(result) == 2


class TestInterpolateStopTimes:
    def test_no_missing_times(self) -> None:
        stop_times = pd.DataFrame({
            "trip_id": ["T1", "T1", "T1"],
            "stop_id": ["S1", "S2", "S3"],
            "stop_sequence": [1, 2, 3],
            "arrival_time": ["08:00:00", "08:10:00", "08:20:00"],
            "departure_time": ["08:00:00", "08:10:00", "08:20:00"],
        })
        result = interpolate_stop_times(stop_times, ["T1"])
        assert len(result) == 3

    def test_interpolate_missing_times(self) -> None:
        stop_times = pd.DataFrame({
            "trip_id": ["T1", "T1", "T1"],
            "stop_id": ["S1", "S2", "S3"],
            "stop_sequence": [1, 2, 3],
            "arrival_time": ["08:00:00", None, "08:20:00"],
            "departure_time": ["08:00:00", None, "08:20:00"],
        })
        result = interpolate_stop_times(stop_times, ["T1"])
        assert len(result) == 3
        # Middle stop should be interpolated to ~08:10:00
        mid = result[result["stop_sequence"] == 2]
        assert mid.iloc[0]["departure_time"] == "08:10:00"


class TestAddUniqueIDs:
    def test_add_trip_id(self) -> None:
        df = pd.DataFrame({
            "trip_id": ["T1", "T2"],
            "route_id": ["R1", "R1"],
        })
        result = add_unique_ids(df, "agency_A", id_col="unique_trip_id")
        assert "unique_trip_id" in result.columns
        assert result.iloc[0]["unique_trip_id"] == "agency_A_T1"
