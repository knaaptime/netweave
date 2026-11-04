"""Test fixtures for netweave."""


import pandas as pd
import pytest

from netweave.io.gtfs import GTFSFeed


def _line_tables(
    n_stops: int = 12,
    departures: tuple[str, ...] = ("08:00:00", "08:20:00", "08:40:00"),
    minutes_per_stop: int = 2,
    route_id: str = "10",
    first_stop: int = 1000,
    first_trip: int = 1,
) -> dict[str, dict[str, list]]:
    """Describe one route as GTFS tables with text values, as a real feed would."""
    stop_ids = [str(first_stop + i) for i in range(n_stops)]
    trip_ids = [str(first_trip + i) for i in range(len(departures))]
    rows = []
    for trip_id, departure in zip(trip_ids, departures, strict=True):
        hours, minutes, _ = (int(part) for part in departure.split(":"))
        for i, stop_id in enumerate(stop_ids):
            total = hours * 60 + minutes + i * minutes_per_stop
            clock = f"{total // 60:02d}:{total % 60:02d}:00"
            rows.append((trip_id, stop_id, str(i + 1), clock, clock))
    trip_col, stop_col, seq_col, arr_col, dep_col = zip(*rows, strict=True)
    return {
        "agency": {"agency_id": ["A"], "agency_name": ["Agency"]},
        "routes": {"route_id": [route_id], "agency_id": ["A"], "route_type": ["3"]},
        "trips": {
            "route_id": [route_id] * len(trip_ids),
            "trip_id": trip_ids,
            "service_id": ["WK"] * len(trip_ids),
        },
        "stops": {
            "stop_id": stop_ids,
            "stop_lat": [f"{37 + i * 0.001:.3f}" for i in range(n_stops)],
            "stop_lon": [f"{-122 - i * 0.001:.3f}" for i in range(n_stops)],
        },
        "stop_times": {
            "trip_id": list(trip_col),
            "stop_id": list(stop_col),
            "stop_sequence": list(seq_col),
            "arrival_time": list(arr_col),
            "departure_time": list(dep_col),
        },
        "calendar": {
            "service_id": ["WK"],
            **{day: ["1"] for day in ("monday", "tuesday", "wednesday", "thursday", "friday")},
            "saturday": ["0"],
            "sunday": ["0"],
            "start_date": ["20260105"],
            "end_date": ["20260628"],
        },
    }


@pytest.fixture
def line_tables():
    """Return a factory for the GTFS tables of a single route."""
    return _line_tables


@pytest.fixture
def write_feed(tmp_path):
    """Return a function that writes GTFS tables to text files in a new folder."""

    def _write(tables: dict[str, dict[str, list]], name: str = "feed"):
        folder = tmp_path / name
        folder.mkdir(parents=True)
        for table, columns in tables.items():
            pd.DataFrame(columns).to_csv(folder / f"{table}.txt", index=False)
        return folder

    return _write


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
