"""Tests for GTFS calendar and service ID selection."""


import pandas as pd
import pytest

from netweave.exceptions import CalendarSelectionError
from netweave.gtfs.calendar import highest_frequency_date, select_service_ids


class TestSelectServiceIDs:
    def test_select_by_day(self) -> None:
        calendar = pd.DataFrame({
            "service_id": ["S1", "S2"],
            "monday": ["1", "0"],
            "tuesday": ["1", "1"],
            "wednesday": ["1", "1"],
            "thursday": ["1", "1"],
            "friday": ["1", "1"],
            "saturday": ["1", "1"],
            "sunday": ["1", "1"],
            "start_date": ["20240101", "20240101"],
            "end_date": ["20241231", "20241231"],
        })
        sids = select_service_ids(calendar, pd.DataFrame(), day="monday")
        assert sids == ["S1"]

    def test_select_by_date(self) -> None:
        calendar = pd.DataFrame({
            "service_id": ["S1"],
            "monday": ["1"],
            "tuesday": ["1"],
            "wednesday": ["1"],
            "thursday": ["1"],
            "friday": ["1"],
            "saturday": ["1"],
            "sunday": ["1"],
            "start_date": ["20240101"],
            "end_date": ["20241231"],
        })
        sids = select_service_ids(calendar, pd.DataFrame(), day="monday", date="20240615")
        assert sids == ["S1"]

    def test_no_service_ids_raises(self) -> None:
        with pytest.raises(CalendarSelectionError):
            select_service_ids(pd.DataFrame(), pd.DataFrame(), day="monday")

    def test_invalid_day_raises(self) -> None:
        calendar = pd.DataFrame({
            "service_id": ["S1"],
            "monday": ["1"],
            "tuesday": ["1"],
            "wednesday": ["1"],
            "thursday": ["1"],
            "friday": ["1"],
            "saturday": ["1"],
            "sunday": ["1"],
            "start_date": ["20240101"],
            "end_date": ["20241231"],
        })
        with pytest.raises(ValueError):
            select_service_ids(calendar, pd.DataFrame(), day="invalid_day")


class TestHighestFrequencyDate:
    def test_highest_frequency(self) -> None:
        trips = pd.DataFrame({
            "trip_id": ["T1", "T2", "T3"],
            "service_id": ["S1", "S1", "S2"],
        })
        calendar = pd.DataFrame({
            "service_id": ["S1", "S2"],
            "monday": ["1", "1"],
            "tuesday": ["1", "1"],
            "wednesday": ["1", "1"],
            "thursday": ["1", "1"],
            "friday": ["1", "1"],
            "saturday": ["1", "1"],
            "sunday": ["1", "1"],
            "start_date": ["20240101", "20240101"],
            "end_date": ["20240107", "20240107"],
        })
        date = highest_frequency_date(trips, calendar, pd.DataFrame())
        assert date == "20240101"
