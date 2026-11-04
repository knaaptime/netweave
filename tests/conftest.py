"""Test fixtures for netweave."""


import pandas as pd
import pytest

from netweave.io.gtfs import GTFSFeed


@pytest.fixture
def minimal_gtfs_feed() -> GTFSFeed:
    """Return a minimal valid GTFS feed for testing."""
    agency = pd.DataFrame({
        "agency_id": ["A1"],
        "agency_name": ["Test Agency"],
    })
    routes = pd.DataFrame({
        "route_id": ["R1"],
        "agency_id": ["A1"],
        "route_type": ["3"],
    })
    trips = pd.DataFrame({
        "route_id": ["R1", "R1"],
        "trip_id": ["T1", "T2"],
        "service_id": ["S1", "S1"],
    })
    stops = pd.DataFrame({
        "stop_id": ["S1", "S2", "S3"],
        "stop_lat": [37.0, 37.1, 37.2],
        "stop_lon": [-122.0, -122.1, -122.2],
    })
    stop_times = pd.DataFrame({
        "trip_id": ["T1", "T1", "T1", "T2", "T2", "T2"],
        "stop_id": ["S1", "S2", "S3", "S1", "S2", "S3"],
        "stop_sequence": [1, 2, 3, 1, 2, 3],
        "arrival_time": ["08:00:00", "08:10:00", "08:20:00", "09:00:00", "09:10:00", "09:20:00"],
        "departure_time": ["08:00:00", "08:10:00", "08:20:00", "09:00:00", "09:10:00", "09:20:00"],
    })
    calendar = pd.DataFrame({
        "service_id": ["S1"],
        "monday": ["1"], "tuesday": ["1"], "wednesday": ["1"],
        "thursday": ["1"], "friday": ["1"], "saturday": ["1"], "sunday": ["1"],
        "start_date": ["20240101"],
        "end_date": ["20241231"],
    })
    return GTFSFeed(
        agency=agency, routes=routes, trips=trips, stops=stops,
        stop_times=stop_times, calendar=calendar
    )


@pytest.fixture
def empty_gtfs_feed() -> GTFSFeed:
    """Return an empty GTFS feed."""
    return GTFSFeed()


@pytest.fixture
def gtfs_feed_with_shapes() -> GTFSFeed:
    """Return a GTFS feed with shapes.txt data."""
    agency = pd.DataFrame({
        "agency_id": ["A1"],
        "agency_name": ["Test Agency"],
    })
    routes = pd.DataFrame({
        "route_id": ["R1"],
        "agency_id": ["A1"],
        "route_type": ["3"],
    })
    trips = pd.DataFrame({
        "route_id": ["R1", "R1"],
        "trip_id": ["T1", "T2"],
        "service_id": ["S1", "S1"],
        "shape_id": ["SH1", "SH1"],
    })
    stops = pd.DataFrame({
        "stop_id": ["S1", "S2", "S3"],
        "stop_lat": [37.0, 37.1, 37.2],
        "stop_lon": [-122.0, -122.1, -122.2],
    })
    stop_times = pd.DataFrame({
        "trip_id": ["T1", "T1", "T1", "T2", "T2", "T2"],
        "stop_id": ["S1", "S2", "S3", "S1", "S2", "S3"],
        "stop_sequence": [1, 2, 3, 1, 2, 3],
        "arrival_time": ["08:00:00", "08:10:00", "08:20:00", "09:00:00", "09:10:00", "09:20:00"],
        "departure_time": ["08:00:00", "08:10:00", "08:20:00", "09:00:00", "09:10:00", "09:20:00"],
    })
    calendar = pd.DataFrame({
        "service_id": ["S1"],
        "monday": ["1"], "tuesday": ["1"], "wednesday": ["1"],
        "thursday": ["1"], "friday": ["1"], "saturday": ["1"], "sunday": ["1"],
        "start_date": ["20240101"],
        "end_date": ["20241231"],
    })
    shapes = pd.DataFrame({
        "shape_id": ["SH1", "SH1", "SH1", "SH1"],
        "shape_pt_lat": [37.0, 37.05, 37.1, 37.2],
        "shape_pt_lon": [-122.0, -122.05, -122.1, -122.2],
        "shape_pt_sequence": [1, 2, 3, 4],
    })
    return GTFSFeed(
        agency=agency, routes=routes, trips=trips, stops=stops,
        stop_times=stop_times, calendar=calendar, shapes=shapes,
    )
