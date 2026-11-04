"""Tests for building a transit network, with feeds read from disk."""

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from netweave.exceptions import EmptyNetworkError, TimeFormatError
from netweave.io.gtfs import load_feed, merge_feeds
from netweave.transform.gtfs import create_transit_network

AM = ("07:00:00", "10:00:00")
MONDAY = "20260105"
PREFIX = "feed_0_"


def plain(identifier):
    return identifier.removeprefix(PREFIX)


def schedule(trips, **extra_tables):
    """Write GTFS tables from {trip: (route, direction, [(stop, time), ...])}.

    A time may be a pair of (arrival, departure), or None where a feed leaves it blank.
    """
    stop_ids = list(dict.fromkeys(row[0] for _, _, rows in trips.values() for row in rows))
    with_direction = any(direction is not None for _, direction, _ in trips.values())
    stop_rows = []
    for trip_id, (_, _, rows) in trips.items():
        for sequence, (stop_id, time) in enumerate(rows, start=1):
            arrival, departure = time if isinstance(time, tuple) else (time, time)
            stop_rows.append((trip_id, stop_id, str(sequence), arrival or "", departure or ""))
    tables = {
        "agency": {"agency_id": ["A"], "agency_name": ["Agency"]},
        "routes": {
            "route_id": list(dict.fromkeys(route for route, _, _ in trips.values())),
        },
        "trips": {
            "route_id": [route for route, _, _ in trips.values()],
            "trip_id": list(trips),
            "service_id": ["WK"] * len(trips),
        },
        "stops": {
            "stop_id": stop_ids,
            "stop_lat": [f"{37 + i * 0.001:.3f}" for i in range(len(stop_ids))],
            "stop_lon": [f"{-122 - i * 0.001:.3f}" for i in range(len(stop_ids))],
        },
        "stop_times": dict(
            zip(
                ("trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"),
                (list(column) for column in zip(*stop_rows, strict=True)),
                strict=True,
            )
        ),
        "calendar": {
            "service_id": ["WK"],
            **{
                day: ["1"]
                for day in (
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                )
            },
            "start_date": ["20260105"],
            "end_date": ["20260628"],
        },
    }
    tables["routes"]["agency_id"] = ["A"] * len(tables["routes"]["route_id"])
    tables["routes"]["route_type"] = ["3"] * len(tables["routes"]["route_id"])
    if with_direction:
        tables["trips"]["direction_id"] = [
            "" if direction is None else direction for _, direction, _ in trips.values()
        ]
    tables.update(extra_tables)
    return tables


@pytest.fixture
def build(write_feed):
    """Build a network from a schedule, written to disk and read back."""

    def _build(trips, timerange=AM, tables=None, **kwargs):
        feed = load_feed(write_feed(tables or schedule(trips)))
        return create_transit_network(feed, date=MONDAY, timerange=timerange, **kwargs)

    return _build


def rides(network):
    """Return {(from stop, to stop): minutes} for the ride edges."""
    stops = network.nodes.set_index("node_id")["stop_id"]
    ride = network.edges[network.edges["edge_type"] == "ride"]
    return {
        (plain(stops[a]), plain(stops[b])): minutes
        for a, b, minutes in zip(ride["from"], ride["to"], ride["minutes"], strict=True)
    }


def boardings(network):
    """Return {(stop, route): minutes} for the boarding edges."""
    nodes = network.nodes.set_index("node_id")
    board = network.edges[network.edges["edge_type"] == "board"]
    return {
        (plain(nodes.loc[b, "stop_id"]), plain(nodes.loc[b, "route_id"])): minutes
        for b, minutes in zip(board["to"], board["minutes"], strict=True)
    }


class TestRideEdges:
    def test_stops_follow_stop_sequence_past_nine(self, line_tables, write_feed) -> None:
        feed = load_feed(write_feed(line_tables(n_stops=12)))
        network = create_transit_network(feed, date=MONDAY, timerange=AM)
        expected = {(str(1000 + i), str(1001 + i)): 2.0 for i in range(11)}
        assert rides(network) == expected

    def test_one_edge_per_connection_however_many_trips(self, line_tables, write_feed) -> None:
        feed = load_feed(write_feed(line_tables(n_stops=4)))
        network = create_transit_network(feed, date=MONDAY, timerange=AM)
        ride = network.edges[network.edges["edge_type"] == "ride"]
        assert len(ride) == 3
        assert not ride.duplicated(["from", "to"]).any()

    def test_ride_time_is_the_mean_across_trips(self, build) -> None:
        network = build(
            {
                "1": ("R", None, [("A", "08:00:00"), ("B", "08:04:00")]),
                "2": ("R", None, [("A", "08:30:00"), ("B", "08:34:00")]),
                "3": ("R", None, [("A", "09:00:00"), ("B", "09:10:00")]),
            }
        )
        assert rides(network) == {("A", "B"): pytest.approx(6.0)}

    def test_ride_time_runs_from_departure_to_next_departure(self, build) -> None:
        network = build(
            {
                "1": (
                    "R",
                    None,
                    [
                        ("A", "08:00:00"),
                        ("B", ("08:05:00", "08:06:00")),
                        ("C", "08:10:00"),
                    ],
                )
            }
        )
        assert rides(network) == {("A", "B"): 6.0, ("B", "C"): 4.0}

    def test_zero_time_connection_keeps_the_route_whole(self, build) -> None:
        network = build(
            {"1": ("R", None, [("A", "08:00:00"), ("B", "08:00:00"), ("C", "08:03:00")])}
        )
        assert rides(network) == {("A", "B"): 0.0, ("B", "C"): 3.0}

    def test_backwards_time_is_dropped_with_a_warning(self, build) -> None:
        with pytest.warns(UserWarning, match="1 "):
            network = build(
                {"1": ("R", None, [("A", "08:05:00"), ("B", "08:00:00"), ("C", "08:03:00")])}
            )
        assert rides(network) == {("B", "C"): 3.0}

    def test_blank_times_are_interpolated_along_the_trip(self, build) -> None:
        network = build({"1": ("R", None, [("A", "08:00:00"), ("B", None), ("C", "08:10:00")])})
        assert rides(network) == {("A", "B"): 5.0, ("B", "C"): 5.0}

    def test_times_past_midnight_are_understood(self, build) -> None:
        network = build(
            {"1": ("R", None, [("A", "25:00:00"), ("B", "25:07:00")])},
            timerange=("24:00:00", "26:00:00"),
        )
        assert rides(network) == {("A", "B"): 7.0}

    def test_malformed_time_raises(self, build) -> None:
        with pytest.raises(TimeFormatError):
            build({"1": ("R", None, [("A", "eight"), ("B", "08:07:00")])})


class TestNodes:
    def test_each_route_at_a_stop_has_its_own_route_stop(self, build) -> None:
        network = build(
            {
                "1": ("R1", None, [("A", "08:00:00"), ("B", "08:05:00")]),
                "2": ("R2", None, [("A", "08:01:00"), ("C", "08:05:00")]),
            }
        )
        nodes = network.nodes
        at_a = nodes[nodes["stop_id"] == f"{PREFIX}A"]
        assert (at_a["node_type"] == "stop").sum() == 1
        assert sorted(at_a.loc[at_a["node_type"] == "route_stop", "route_id"]) == [
            f"{PREFIX}R1",
            f"{PREFIX}R2",
        ]

    def test_each_direction_at_a_stop_has_its_own_route_stop(self, build) -> None:
        network = build(
            {
                "1": ("R", "0", [("A", "08:00:00"), ("B", "08:05:00")]),
                "2": ("R", "1", [("B", "08:10:00"), ("A", "08:15:00")]),
            }
        )
        route_stops = network.nodes[network.nodes["node_type"] == "route_stop"]
        at_a = route_stops[route_stops["stop_id"] == f"{PREFIX}A"]
        assert sorted(at_a["direction_id"]) == ["0", "1"]

    def test_without_direction_a_route_has_one_route_stop_per_stop(self, build) -> None:
        network = build(
            {
                "1": ("R", None, [("A", "08:00:00"), ("B", "08:05:00")]),
                "2": ("R", None, [("B", "08:10:00"), ("A", "08:15:00")]),
            }
        )
        route_stops = network.nodes[network.nodes["node_type"] == "route_stop"]
        assert len(route_stops) == 2
        assert route_stops["direction_id"].isna().all()

    def test_node_table_shape(self, build) -> None:
        network = build({"1": ("R", None, [("A", "08:00:00"), ("B", "08:05:00")])})
        nodes = network.nodes
        assert list(nodes.columns) == [
            "node_id",
            "x",
            "y",
            "node_type",
            "stop_id",
            "route_id",
            "direction_id",
            "feed",
        ]
        assert nodes["node_id"].is_unique
        assert pd.api.types.is_integer_dtype(nodes["node_id"])
        assert nodes.loc[nodes["stop_id"] == f"{PREFIX}B", "x"].tolist() == [-122.001] * 2
        assert nodes.loc[nodes["stop_id"] == f"{PREFIX}B", "y"].tolist() == [37.001] * 2
        assert set(nodes["feed"]) == {"feed_0"}

    def test_edge_table_shape(self, build) -> None:
        network = build({"1": ("R", None, [("A", "08:00:00"), ("B", "08:05:00")])})
        assert list(network.edges.columns) == [
            "from",
            "to",
            "edge_type",
            "minutes",
            "route_id",
            "direction_id",
            "geometry",
        ]
        assert isinstance(network.edges, gpd.GeoDataFrame)
        assert network.edges.crs.to_epsg() == 4326


class TestWait:
    def test_wait_is_half_the_mean_headway(self, build) -> None:
        network = build(
            {
                "1": ("R", None, [("A", "08:00:00"), ("B", "08:02:00")]),
                "2": ("R", None, [("A", "08:10:00"), ("B", "08:12:00")]),
                "3": ("R", None, [("A", "08:25:00"), ("B", "08:27:00")]),
            }
        )
        # Gaps of 10 and 15 minutes: mean headway 12.5, wait 6.25.
        assert boardings(network) == {("A", "R"): pytest.approx(6.25)}

    def test_single_departure_counts_the_window_as_its_headway(self, build) -> None:
        network = build({"1": ("R", None, [("A", "08:00:00"), ("B", "08:02:00")])})
        # The window runs three hours: headway 180, wait 90.
        assert boardings(network) == {("A", "R"): pytest.approx(90.0)}

    def test_each_route_waits_separately(self, build) -> None:
        network = build(
            {
                "1": ("FAST", None, [("A", "08:00:00"), ("B", "08:02:00")]),
                "2": ("FAST", None, [("A", "08:10:00"), ("B", "08:12:00")]),
                "3": ("SLOW", None, [("A", "08:00:00"), ("C", "08:02:00")]),
                "4": ("SLOW", None, [("A", "09:00:00"), ("C", "09:02:00")]),
            }
        )
        assert boardings(network) == {
            ("A", "FAST"): pytest.approx(5.0),
            ("A", "SLOW"): pytest.approx(30.0),
        }

    def test_opposite_directions_do_not_pool_their_departures(self, build) -> None:
        network = build(
            {
                "1": ("R", "0", [("A", "08:00:00"), ("B", "08:02:00")]),
                "2": ("R", "0", [("A", "08:20:00"), ("B", "08:22:00")]),
                "3": ("R", "1", [("A", "08:10:00"), ("C", "08:12:00")]),
                "4": ("R", "1", [("A", "08:30:00"), ("C", "08:32:00")]),
            }
        )
        board = network.edges[network.edges["edge_type"] == "board"]
        assert board["minutes"].tolist() == pytest.approx([10.0, 10.0])

    def test_departures_outside_the_window_do_not_count(self, build) -> None:
        network = build(
            {
                "1": ("R", None, [("A", "06:00:00"), ("B", "06:02:00")]),
                "2": ("R", None, [("A", "08:00:00"), ("B", "08:02:00")]),
                "3": ("R", None, [("A", "08:20:00"), ("B", "08:22:00")]),
            }
        )
        assert boardings(network) == {("A", "R"): pytest.approx(10.0)}

    def test_trips_leaving_at_the_same_moment_count_once(self, build) -> None:
        network = build(
            {
                "1": ("R", None, [("A", "08:00:00"), ("B", "08:02:00")]),
                "2": ("R", None, [("A", "08:00:00"), ("B", "08:02:00")]),
                "3": ("R", None, [("A", "08:20:00"), ("B", "08:22:00")]),
            }
        )
        assert boardings(network) == {("A", "R"): pytest.approx(10.0)}

    def test_wait_can_be_turned_off(self, build) -> None:
        network = build(
            {"1": ("R", None, [("A", "08:00:00"), ("B", "08:02:00")])}, use_headways=False
        )
        assert boardings(network) == {("A", "R"): 0.0}

    def test_alighting_costs_nothing(self, build) -> None:
        network = build({"1": ("R", None, [("A", "08:00:00"), ("B", "08:02:00")])})
        alight = network.edges[network.edges["edge_type"] == "alight"]
        assert alight["minutes"].tolist() == [0.0]

    def test_no_boarding_at_the_last_stop_or_alighting_at_the_first(self, build) -> None:
        network = build({"1": ("R", None, [("A", "08:00:00"), ("B", "08:02:00")])})
        nodes = network.nodes.set_index("node_id")
        edges = network.edges
        board = edges[edges["edge_type"] == "board"]
        alight = edges[edges["edge_type"] == "alight"]
        assert [plain(nodes.loc[n, "stop_id"]) for n in board["from"]] == ["A"]
        assert [plain(nodes.loc[n, "stop_id"]) for n in alight["to"]] == ["B"]

    def test_boarding_and_alighting_connect_a_stop_to_its_route_stops(self, build) -> None:
        network = build(
            {"1": ("R", None, [("A", "08:00:00"), ("B", "08:02:00"), ("C", "08:04:00")])}
        )
        nodes = network.nodes.set_index("node_id")
        edges = network.edges
        board = edges[edges["edge_type"] == "board"]
        assert (nodes.loc[board["from"], "node_type"] == "stop").all()
        assert (nodes.loc[board["to"], "node_type"] == "route_stop").all()
        assert (
            nodes.loc[board["from"], "stop_id"].to_numpy()
            == nodes.loc[board["to"], "stop_id"].to_numpy()
        ).all()


class TestFrequencies:
    def frequency_tables(self):
        return schedule(
            {"T": ("R", None, [("A", "00:00:00"), ("B", "00:04:00"), ("C", "00:06:00")])},
            frequencies={
                "trip_id": ["T"],
                "start_time": ["07:00:00"],
                "end_time": ["09:00:00"],
                "headway_secs": ["300"],
            },
        )

    def test_template_trip_becomes_departures_at_its_headway(self, build) -> None:
        network = build(None, tables=self.frequency_tables())
        assert boardings(network) == {
            ("A", "R"): pytest.approx(2.5),
            ("B", "R"): pytest.approx(2.5),
        }
        assert rides(network) == {("A", "B"): 4.0, ("B", "C"): 2.0}

    def test_departures_stop_at_the_end_time(self, build) -> None:
        tables = self.frequency_tables()
        tables["frequencies"]["end_time"] = ["07:10:00"]
        tables["frequencies"]["headway_secs"] = ["600"]
        network = build(None, tables=tables)
        # 07:00 only, because 07:10 is the end of the period: a single departure.
        assert boardings(network)[("A", "R")] == pytest.approx(90.0)

    def test_ordinary_trips_in_the_same_feed_are_untouched(self, build) -> None:
        tables = schedule(
            {
                "T": ("R1", None, [("A", "00:00:00"), ("B", "00:04:00")]),
                "U": ("R2", None, [("A", "08:00:00"), ("C", "08:03:00")]),
            },
            frequencies={
                "trip_id": ["T"],
                "start_time": ["07:00:00"],
                "end_time": ["09:00:00"],
                "headway_secs": ["600"],
            },
        )
        network = build(None, tables=tables)
        assert boardings(network) == {
            ("A", "R1"): pytest.approx(5.0),
            ("A", "R2"): pytest.approx(90.0),
        }


class TestWindow:
    def test_timerange_is_required(self, line_tables, write_feed) -> None:
        feed = load_feed(write_feed(line_tables()))
        with pytest.raises(TypeError, match="timerange"):
            create_transit_network(feed, date=MONDAY)

    def test_window_must_run_forwards(self, build) -> None:
        with pytest.raises(ValueError, match="timerange"):
            build(
                {"1": ("R", None, [("A", "08:00:00"), ("B", "08:02:00")])},
                timerange=("10:00:00", "07:00:00"),
            )

    def test_no_departures_in_the_window_raises(self, build) -> None:
        with pytest.raises(EmptyNetworkError):
            build(
                {"1": ("R", None, [("A", "08:00:00"), ("B", "08:02:00")])},
                timerange=("20:00:00", "21:00:00"),
            )

    def test_one_stop_inside_the_window_makes_no_network(self, build) -> None:
        with pytest.raises(EmptyNetworkError):
            build(
                {"1": ("R", None, [("A", "06:59:00"), ("B", "07:00:00")])},
            )

    def test_metadata_records_the_window_and_wait_setting(self, build) -> None:
        network = build({"1": ("R", None, [("A", "08:00:00"), ("B", "08:02:00")])})
        assert network.metadata["time_window"] == list(AM)
        assert network.metadata["use_headways"] is True


class TestPrune:
    TRIP = {
        "1": (
            "R",
            None,
            [
                ("A", "08:00:00"),
                ("B", "08:01:00"),
                ("C", "08:03:00"),
                ("D", "08:06:00"),
            ],
        )
    }
    # A, B, C and D sit at longitudes -122.000, -122.001, -122.002 and -122.003.
    AROUND_A_AND_B = (-122.0015, 36.9, -121.9, 37.0015)

    def test_bounding_box(self, build) -> None:
        network = build(self.TRIP, prune=self.AROUND_A_AND_B)
        assert rides(network) == {("A", "B"): 1.0}

    def test_total_bounds_array(self, build) -> None:
        network = build(self.TRIP, prune=np.array(self.AROUND_A_AND_B))
        assert rides(network) == {("A", "B"): 1.0}

    def test_polygon(self, build) -> None:
        network = build(self.TRIP, prune=box(*self.AROUND_A_AND_B))
        assert rides(network) == {("A", "B"): 1.0}

    def test_projected_boundary_is_reprojected(self, build) -> None:
        area = gpd.GeoDataFrame(geometry=[box(*self.AROUND_A_AND_B)], crs=4326).to_crs(3857)
        network = build(self.TRIP, prune=area)
        assert rides(network) == {("A", "B"): 1.0}

    def test_route_leaving_and_returning_bridges_the_gap(self, build) -> None:
        trip = {
            "1": (
                "R",
                None,
                [
                    ("A", "08:00:00"),
                    ("B", "08:01:00"),
                    ("C", "08:03:00"),
                    ("D", "08:06:00"),
                ],
            )
        }
        keep_a_and_d = gpd.GeoDataFrame(
            geometry=[
                box(-122.0005, 36.9, -121.9, 37.0005),
                box(-122.0035, 37.0025, -122.0025, 37.0035),
            ],
            crs=4326,
        )
        network = build(trip, prune=keep_a_and_d)
        assert rides(network) == {("A", "D"): 6.0}

    def test_caller_feed_is_unchanged(self, write_feed) -> None:
        feed = load_feed(write_feed(schedule(self.TRIP)))
        create_transit_network(feed, date=MONDAY, timerange=AM, prune=self.AROUND_A_AND_B)
        assert len(feed.stops) == 4
        assert len(feed.routes) == 1

    def test_merged_caller_feed_is_unchanged(self, write_feed) -> None:
        merged = merge_feeds([load_feed(write_feed(schedule(self.TRIP)))])
        create_transit_network(merged, date=MONDAY, timerange=AM, prune=self.AROUND_A_AND_B)
        assert len(merged.stops) == 4
        assert len(merged.routes) == 1

    def test_area_without_stops_raises(self, build) -> None:
        with pytest.raises(EmptyNetworkError):
            build(self.TRIP, prune=(0.0, 0.0, 1.0, 1.0))

    def test_malformed_bounding_box_is_refused(self, build) -> None:
        with pytest.raises(ValueError, match="prune"):
            build(self.TRIP, prune=(0.0, 0.0, 1.0))


class TestStopsWithoutCoordinates:
    def test_they_are_skipped_with_a_warning(self, write_feed) -> None:
        tables = schedule(
            {"1": ("R", None, [("A", "08:00:00"), ("B", "08:02:00"), ("C", "08:05:00")])}
        )
        tables["stops"]["stop_lat"][1] = ""
        tables["stops"]["stop_lon"][1] = ""
        with pytest.warns(UserWarning, match="coordinates"):
            network = create_transit_network(
                load_feed(write_feed(tables)), date=MONDAY, timerange=AM
            )
        assert rides(network) == {("A", "C"): 5.0}


class TestGeometry:
    @staticmethod
    def straight_stops():
        """Three stops due east along a line, on a schedule with one trip."""
        tables = schedule(
            {
                "1": (
                    "R",
                    None,
                    [("A", "08:00:00"), ("B", "08:02:00"), ("C", "08:04:00")],
                )
            }
        )
        tables["stops"]["stop_lat"] = ["0.0", "0.0", "0.0"]
        tables["stops"]["stop_lon"] = ["0.0", "1.5", "3.0"]
        return tables

    @staticmethod
    def ride_lines(network):
        stops = network.nodes.set_index("node_id")["stop_id"]
        ride = network.edges[network.edges["edge_type"] == "ride"]
        return {
            (plain(stops[a]), plain(stops[b])): list(line.coords)
            for a, b, line in zip(ride["from"], ride["to"], ride["geometry"], strict=True)
        }

    def test_straight_line_without_shapes(self, build) -> None:
        network = build(None, tables=self.straight_stops())
        assert self.ride_lines(network)[("A", "B")] == [(0.0, 0.0), (1.5, 0.0)]

    def test_shape_is_cut_between_the_two_stops(self, build) -> None:
        tables = self.straight_stops()
        tables["trips"]["shape_id"] = ["S"]
        tables["shapes"] = {
            "shape_id": ["S"] * 4,
            "shape_pt_lat": ["0"] * 4,
            "shape_pt_lon": ["0", "1", "2", "3"],
            "shape_pt_sequence": ["1", "2", "3", "4"],
        }
        lines = self.ride_lines(build(None, tables=tables))
        assert lines[("A", "B")] == [(0.0, 0.0), (1.0, 0.0), (1.5, 0.0)]
        assert lines[("B", "C")] == [(1.5, 0.0), (2.0, 0.0), (3.0, 0.0)]

    def test_shape_points_follow_their_sequence_past_nine(self, build) -> None:
        tables = self.straight_stops()
        tables["trips"]["shape_id"] = ["S"]
        longitudes = [f"{i * 0.3:.1f}" for i in range(11)]
        tables["shapes"] = {
            "shape_id": ["S"] * 11,
            "shape_pt_lat": ["0"] * 11,
            "shape_pt_lon": longitudes,
            "shape_pt_sequence": [str(i + 1) for i in range(11)],
        }
        lines = self.ride_lines(build(None, tables=tables))
        assert lines[("A", "B")][1] == (0.3, 0.0)

    def test_stops_out_of_order_along_the_shape_get_a_straight_line(self, build) -> None:
        tables = self.straight_stops()
        tables["trips"]["shape_id"] = ["S"]
        tables["shapes"] = {
            "shape_id": ["S"] * 2,
            "shape_pt_lat": ["0"] * 2,
            "shape_pt_lon": ["3", "0"],
            "shape_pt_sequence": ["1", "2"],
        }
        lines = self.ride_lines(build(None, tables=tables))
        assert lines[("A", "B")] == [(0.0, 0.0), (1.5, 0.0)]

    def test_most_common_shape_is_used(self, build) -> None:
        tables = schedule(
            {
                "1": ("R", None, [("A", "08:00:00"), ("B", "08:02:00")]),
                "2": ("R", None, [("A", "08:20:00"), ("B", "08:22:00")]),
                "3": ("R", None, [("A", "08:40:00"), ("B", "08:42:00")]),
            }
        )
        tables["stops"]["stop_lat"] = ["0.0", "0.0"]
        tables["stops"]["stop_lon"] = ["0.0", "1.0"]
        tables["trips"]["shape_id"] = ["RARE", "USUAL", "USUAL"]
        tables["shapes"] = {
            "shape_id": ["RARE"] * 3 + ["USUAL"] * 3,
            "shape_pt_lat": ["0", "5", "0", "0", "1", "0"],
            "shape_pt_lon": ["0", "0.5", "1", "0", "0.5", "1"],
            "shape_pt_sequence": ["1", "2", "3", "1", "2", "3"],
        }
        lines = self.ride_lines(build(None, tables=tables))
        assert (0.5, 1.0) in lines[("A", "B")]

    def test_boarding_and_alighting_have_no_geometry(self, build) -> None:
        network = build(None, tables=self.straight_stops())
        edges = network.edges
        assert edges.loc[edges["edge_type"].isin(["board", "alight"]), "geometry"].isna().all()
