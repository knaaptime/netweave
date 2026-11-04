"""Tests for GTFS headway computation."""


import pandas as pd

from netweave.transform.headways import compute_headways


class TestComputeHeadways:
    def test_basic_headways(self) -> None:
        stop_times = pd.DataFrame({
            "trip_id": ["T1", "T2", "T3"],
            "stop_id": ["S1", "S1", "S1"],
            "stop_sequence": [1, 1, 1],
            "departure_time": ["08:00:00", "08:10:00", "08:25:00"],
        })
        trips = pd.DataFrame({
            "trip_id": ["T1", "T2", "T3"],
            "route_id": ["R1", "R1", "R1"],
        })
        routes = pd.DataFrame({
            "route_id": ["R1"],
            "route_type": ["3"],
        })
        stops = pd.DataFrame({
            "stop_id": ["S1"],
            "stop_lat": [37.0],
            "stop_lon": [-122.0],
        })
        result = compute_headways(stop_times, trips, routes, stops)
        assert len(result) == 1
        assert result.iloc[0]["route_id"] == "R1"
        assert result.iloc[0]["stop_id"] == "S1"
        # Headways: 10 min, 15 min -> mean = 12.5 min
        assert result.iloc[0]["mean"] == 12.5

    def test_no_valid_headways(self) -> None:
        stop_times = pd.DataFrame({
            "trip_id": ["T1"],
            "stop_id": ["S1"],
            "stop_sequence": [1],
            "departure_time": ["08:00:00"],
        })
        trips = pd.DataFrame({
            "trip_id": ["T1"],
            "route_id": ["R1"],
        })
        routes = pd.DataFrame({
            "route_id": ["R1"],
            "route_type": ["3"],
        })
        stops = pd.DataFrame({
            "stop_id": ["S1"],
            "stop_lat": [37.0],
            "stop_lon": [-122.0],
        })
        result = compute_headways(stop_times, trips, routes, stops)
        assert result.empty
