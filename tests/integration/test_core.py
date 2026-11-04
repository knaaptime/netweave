"""Tests for integrate, using real pandarm networks and worked trip costs.

The pedestrian network is a straight street in UTM zone 10, in meters. At the
default 3 mph, one minute of walking covers 80.4672 m.
"""

import json

import geopandas as gpd
import numpy as np
import pandarm
import pandas as pd
import pyproj
import pytest
from helpers import schedule
from shapely.geometry import LineString, Point

from netweave.exceptions import EmptyNetworkError, NetworkIntegrationError
from netweave.integration.core import integrate
from netweave.io.gtfs import load_feed
from netweave.transform.gtfs import create_transit_network
from netweave.types import TransitNetwork

UTM = 32610
X0, Y0 = 550_000.0, 4_180_000.0
MINUTE = 80.4672
BLOCK = 10 * MINUTE
AM = ("07:00:00", "10:00:00")
MONDAY = "20260105"
WEST, MIDDLE, EAST = 900, 901, 902


def street(crs=UTM, twoway=False, impedances=None, geometry=True):
    """Three pedestrian nodes in a line, ten walking minutes apart, walkable both ways."""
    x = pd.Series([X0, X0 + BLOCK, X0 + 2 * BLOCK], index=[WEST, MIDDLE, EAST], dtype=float)
    y = pd.Series([Y0, Y0, Y0], index=[WEST, MIDDLE, EAST], dtype=float)
    if twoway:
        origin, destination = [WEST, MIDDLE], [MIDDLE, EAST]
    else:
        origin = [WEST, MIDDLE, MIDDLE, EAST]
        destination = [MIDDLE, WEST, EAST, MIDDLE]
    weights = impedances or {"length": [BLOCK] * len(origin)}
    lines = None
    if geometry:
        lines = gpd.GeoSeries(
            [
                LineString([(x[a], y[a]), (x[b], y[b])])
                for a, b in zip(origin, destination, strict=True)
            ],
            crs=crs,
        )
    return pandarm.Network(
        x,
        y,
        pd.Series(origin),
        pd.Series(destination),
        pd.DataFrame(weights),
        twoway=twoway,
        edge_geom=lines,
        crs=crs,
    )


def place(x_offset, y_offset, crs=UTM, x0=X0, y0=Y0):
    """Return the longitude and latitude of a point near the street's west end."""
    point = gpd.GeoSeries([Point(x0 + x_offset, y0 + y_offset)], crs=crs).to_crs(4326).iloc[0]
    return f"{point.x:.9f}", f"{point.y:.9f}"


# Stops one minute's walk north of the west and east ends of the street.
STOP_POSITIONS = {
    "A": place(0, MINUTE),
    "B": place(2 * BLOCK, MINUTE),
}


def tables_at(trips, positions=None):
    """Return GTFS tables with stops placed at known positions."""
    tables = schedule(trips)
    where = positions or STOP_POSITIONS
    tables["stops"]["stop_lon"] = [where[stop][0] for stop in tables["stops"]["stop_id"]]
    tables["stops"]["stop_lat"] = [where[stop][1] for stop in tables["stops"]["stop_id"]]
    return tables


@pytest.fixture
def transit_from(write_feed):
    """Build a transit network from a schedule, written to disk and read back."""
    counter = iter(range(100))

    def _build(trips, positions=None, **kwargs):
        folder = write_feed(tables_at(trips, positions), name=f"feed{next(counter)}")
        return create_transit_network(load_feed(folder), date=MONDAY, timerange=AM, **kwargs)

    return _build


# Route R runs from A to B in three minutes, every twenty minutes: a wait of ten.
EVERY_TWENTY = {
    "1": ("R", None, [("A", "08:00:00"), ("B", "08:03:00")]),
    "2": ("R", None, [("A", "08:20:00"), ("B", "08:23:00")]),
}


def cost(network, origin, destination):
    return network.shortest_path_length(origin, destination, imp_name="minutes")


def stop_node(network, stop):
    nodes = network.nodes_df
    return nodes[(nodes["node_type"] == "stop") & (nodes["stop_id"] == f"feed_0_{stop}")].index[0]


class TestTripCosts:
    def test_walk_wait_ride_and_walk_add_up(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        # 1 walk + 10 wait + 3 ride + 0 alight + 1 walk.
        assert cost(network, WEST, EAST) == pytest.approx(15.0, abs=0.01)

    def test_walking_wins_when_the_wait_is_long(self, transit_from) -> None:
        hourly = {
            "1": ("R", None, [("A", "08:00:00"), ("B", "08:03:00")]),
            "2": ("R", None, [("A", "09:00:00"), ("B", "09:03:00")]),
        }
        network = integrate(transit_from(hourly), street())
        # 1 + 30 + 3 + 1 = 35 by transit, against 20 on foot.
        assert cost(network, WEST, EAST) == pytest.approx(20.0, abs=0.01)

    def test_no_wait_when_headways_are_off(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY, use_headways=False), street())
        assert cost(network, WEST, EAST) == pytest.approx(5.0, abs=0.01)

    def test_transit_runs_one_way(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        assert cost(network, EAST, WEST) == pytest.approx(20.0, abs=0.01)

    def test_changing_routes_at_a_stop_costs_the_wait_and_no_walking(self, transit_from) -> None:
        trips = {
            "1": ("R1", None, [("A", "08:00:00"), ("M", "08:02:00")]),
            "2": ("R1", None, [("A", "08:20:00"), ("M", "08:22:00")]),
            "3": ("R2", None, [("M", "08:05:00"), ("B", "08:09:00")]),
            "4": ("R2", None, [("M", "08:45:00"), ("B", "08:49:00")]),
        }
        positions = {**STOP_POSITIONS, "M": place(BLOCK, 4 * MINUTE)}
        far_apart = street(impedances={"length": [100 * BLOCK] * 4})
        network = integrate(transit_from(trips, positions), far_apart)
        # 10 wait + 2 ride + 0 alight + 20 wait + 4 ride, with no walk at M.
        assert cost(network, stop_node(network, "A"), stop_node(network, "B")) == pytest.approx(
            36.0, abs=0.01
        )


class TestPedestrianInput:
    def test_only_a_pandarm_network_is_accepted(self, transit_from) -> None:
        with pytest.raises(TypeError, match=r"pandarm\.Network"):
            integrate(transit_from(EVERY_TWENTY), pd.DataFrame())

    def test_empty_transit_network_is_refused(self) -> None:
        empty = TransitNetwork(edges=pd.DataFrame(), nodes=pd.DataFrame())
        with pytest.raises(EmptyNetworkError):
            integrate(empty, street())

    def test_pedestrian_node_ids_are_kept(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        walkers = network.nodes_df[network.nodes_df["node_type"] == "pedestrian"]
        assert walkers.index.tolist() == [WEST, MIDDLE, EAST]
        walk = network.edges_df[network.edges_df["edge_type"] == "walk"]
        assert set(walk["from"]) == {WEST, MIDDLE, EAST}

    def test_transit_node_ids_are_integers_above_the_pedestrian_ids(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        transit = network.nodes_df[network.nodes_df["node_type"] != "pedestrian"]
        assert pd.api.types.is_integer_dtype(network.nodes_df.index)
        assert transit.index.min() > EAST
        assert network.nodes_df.index.is_unique

    def test_text_pedestrian_ids_are_refused(self, transit_from) -> None:
        text = pandarm.Network(
            pd.Series([X0, X0 + 1], index=["a", "b"]),
            pd.Series([Y0, Y0], index=["a", "b"]),
            pd.Series(["a"]),
            pd.Series(["b"]),
            pd.DataFrame({"length": [1.0]}),
            twoway=False,
            crs=UTM,
        )
        with pytest.raises(NetworkIntegrationError, match="integer"):
            integrate(transit_from(EVERY_TWENTY), text)

    def test_two_way_input_can_be_walked_in_both_directions(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street(twoway=True))
        assert cost(network, EAST, WEST) == pytest.approx(20.0, abs=0.01)
        walk = network.edges_df[network.edges_df["edge_type"] == "walk"]
        assert len(walk) == 4

    def test_two_way_expansion_reverses_geometry(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street(twoway=True))
        walk = network.edges_df[network.edges_df["edge_type"] == "walk"]
        back = walk[(walk["from"] == MIDDLE) & (walk["to"] == WEST)].geometry.iloc[0]
        assert back.coords[0][0] > back.coords[-1][0]

    def test_input_without_geometry_is_accepted(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street(geometry=False))
        assert cost(network, WEST, EAST) == pytest.approx(15.0, abs=0.01)

    def test_input_network_is_unchanged(self, transit_from) -> None:
        pedestrian = street()
        integrate(transit_from(EVERY_TWENTY), pedestrian)
        assert list(pedestrian.nodes_df.columns) == ["x", "y", "geometry"]
        assert len(pedestrian.edges_df) == 4

    def test_parallel_edges_collapse_to_the_cheapest(self, transit_from) -> None:
        x = pd.Series([X0, X0 + BLOCK], index=[WEST, MIDDLE])
        y = pd.Series([Y0, Y0], index=[WEST, MIDDLE])
        parallel = pandarm.Network(
            x,
            y,
            pd.Series([WEST, WEST]),
            pd.Series([MIDDLE, MIDDLE]),
            pd.DataFrame({"length": [2 * BLOCK, BLOCK]}),
            twoway=False,
            crs=UTM,
        )
        positions = {"A": place(0, MINUTE), "B": place(BLOCK, MINUTE)}
        network = integrate(transit_from(EVERY_TWENTY, positions), parallel)
        walk = network.edges_df[network.edges_df["edge_type"] == "walk"]
        assert walk["minutes"].tolist() == pytest.approx([10.0])


class TestPedestrianCost:
    def test_meters_are_walked_at_the_given_speed(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street(), walk_speed_mph=6.0)
        # Walking takes half as long: 0.5 + 10 + 3 + 0.5 = 14 by transit, and 10 on foot.
        assert cost(network, WEST, EAST) == pytest.approx(10.0, abs=0.01)

    def test_minutes_are_used_directly(self, transit_from) -> None:
        pedestrian = street(impedances={"time": [7.0] * 4})
        network = integrate(transit_from(EVERY_TWENTY), pedestrian, pedestrian_unit="minutes")
        assert cost(network, WEST, MIDDLE) == pytest.approx(7.0, abs=0.01)

    def test_seconds_are_converted(self, transit_from) -> None:
        pedestrian = street(impedances={"time": [120.0] * 4})
        network = integrate(transit_from(EVERY_TWENTY), pedestrian, pedestrian_unit="seconds")
        assert cost(network, WEST, MIDDLE) == pytest.approx(2.0, abs=0.01)

    def test_unknown_unit_is_refused(self, transit_from) -> None:
        with pytest.raises(ValueError, match="furlongs"):
            integrate(transit_from(EVERY_TWENTY), street(), pedestrian_unit="furlongs")

    def test_several_impedances_must_be_named(self, transit_from) -> None:
        both = street(impedances={"length": [BLOCK] * 4, "time": [3.0] * 4})
        with pytest.raises(ValueError, match="pedestrian_impedance"):
            integrate(transit_from(EVERY_TWENTY), both)

    def test_named_impedance_is_used(self, transit_from) -> None:
        both = street(impedances={"length": [BLOCK] * 4, "time": [3.0] * 4})
        network = integrate(
            transit_from(EVERY_TWENTY),
            both,
            pedestrian_impedance="time",
            pedestrian_unit="minutes",
        )
        assert cost(network, WEST, MIDDLE) == pytest.approx(3.0, abs=0.01)

    def test_unknown_impedance_is_refused(self, transit_from) -> None:
        with pytest.raises(ValueError, match="comfort"):
            integrate(transit_from(EVERY_TWENTY), street(), pedestrian_impedance="comfort")

    @pytest.mark.parametrize("bad", [np.nan, np.inf, -1.0, 1e9])
    def test_costs_pandarm_would_misread_are_refused(self, transit_from, bad) -> None:
        pedestrian = street(impedances={"time": [1.0, 1.0, 1.0, bad]})
        with pytest.raises(NetworkIntegrationError, match="minutes"):
            integrate(transit_from(EVERY_TWENTY), pedestrian, pedestrian_unit="minutes")


class TestCoordinateSystems:
    def test_network_keeps_the_pedestrian_crs(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        assert network.crs == UTM
        assert network.edges_df.crs.to_epsg() == UTM

    def test_network_reprojected_by_pandarm_is_read_correctly(self, transit_from) -> None:
        # pandarm's to_crs leaves Network.crs at 4326 and sets the real CRS on nodes_df.
        reprojected = street().to_crs(4326).to_crs(UTM)
        network = integrate(transit_from(EVERY_TWENTY), reprojected)
        assert pyproj.CRS.from_user_input(network.crs).to_epsg() == UTM
        assert network.nodes_df.loc[stop_node(network, "A"), "x"] == pytest.approx(X0, abs=0.01)
        assert cost(network, WEST, EAST) == pytest.approx(15.0, abs=0.01)

    def test_stops_are_reprojected_into_it(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        node = network.nodes_df.loc[stop_node(network, "A")]
        assert node["x"] == pytest.approx(X0, abs=0.01)
        assert node["y"] == pytest.approx(Y0 + MINUTE, abs=0.01)

    def test_ride_geometry_is_reprojected(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        ride = network.edges_df[network.edges_df["edge_type"] == "ride"].geometry.iloc[0]
        assert ride.length == pytest.approx(2 * BLOCK, abs=0.1)

    def test_geographic_network_measures_distance_on_the_sphere(self, write_feed) -> None:
        pedestrian = pandarm.Network(
            pd.Series([0.0, 0.001], index=[WEST, MIDDLE]),
            pd.Series([0.0, 0.0], index=[WEST, MIDDLE]),
            pd.Series([WEST, MIDDLE]),
            pd.Series([MIDDLE, WEST]),
            pd.DataFrame({"length": [100.0, 100.0]}),
            twoway=False,
            crs=4326,
        )
        tables = schedule(EVERY_TWENTY)
        tables["stops"]["stop_lon"] = ["0.0", "0.001"]
        tables["stops"]["stop_lat"] = ["0.001", "0.001"]
        transit = create_transit_network(load_feed(write_feed(tables)), date=MONDAY, timerange=AM)
        network = integrate(transit, pedestrian)
        # 0.001 degrees on a sphere of radius 6371008.8 m is 111.195 m: 1.3819 minutes.
        assert cost(network, WEST, stop_node(network, "A")) == pytest.approx(1.3819, abs=0.01)

    def test_projected_distance_respects_the_unit_of_the_crs(self, write_feed) -> None:
        feet = 2229  # California zone 5, in US survey feet
        origin = gpd.GeoSeries([Point(-118.25, 34.05)], crs=4326).to_crs(feet).iloc[0]
        pedestrian = pandarm.Network(
            pd.Series([origin.x, origin.x + 5000.0], index=[WEST, MIDDLE]),
            pd.Series([origin.y, origin.y], index=[WEST, MIDDLE]),
            pd.Series([WEST, MIDDLE]),
            pd.Series([MIDDLE, WEST]),
            pd.DataFrame({"length": [1524.0, 1524.0]}),
            twoway=False,
            crs=feet,
        )
        positions = {
            "A": place(0, 1000.0, crs=feet, x0=origin.x, y0=origin.y),
            "B": place(5000.0, 1000.0, crs=feet, x0=origin.x, y0=origin.y),
        }
        tables = tables_at(EVERY_TWENTY, positions)
        transit = create_transit_network(load_feed(write_feed(tables)), date=MONDAY, timerange=AM)
        network = integrate(transit, pedestrian)
        # 1000 US survey feet is 304.8006 m: 3.788 minutes, and within the default 800 m.
        assert cost(network, WEST, stop_node(network, "A")) == pytest.approx(3.788, abs=0.01)


class TestConnectors:
    def test_each_stop_joins_its_nearest_pedestrian_node_both_ways(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        connectors = network.edges_df[network.edges_df["edge_type"] == "connector"]
        west_stop, east_stop = stop_node(network, "A"), stop_node(network, "B")
        pairs = set(zip(connectors["from"], connectors["to"], strict=True))
        assert pairs == {(west_stop, WEST), (WEST, west_stop), (east_stop, EAST), (EAST, east_stop)}
        assert connectors["minutes"].tolist() == pytest.approx([1.0] * 4, abs=0.001)

    def test_route_stops_have_no_connectors(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        nodes = network.nodes_df
        route_stops = nodes[nodes["node_type"] == "route_stop"].index
        connectors = network.edges_df[network.edges_df["edge_type"] == "connector"]
        assert not connectors["from"].isin(route_stops).any()
        assert not connectors["to"].isin(route_stops).any()

    def test_stranded_stop_stays_in_the_ride_chain_with_a_warning(self, transit_from) -> None:
        trips = {
            "1": ("R", None, [("A", "08:00:00"), ("FAR", "08:02:00"), ("B", "08:03:00")]),
            "2": ("R", None, [("A", "08:20:00"), ("FAR", "08:22:00"), ("B", "08:23:00")]),
        }
        positions = {**STOP_POSITIONS, "FAR": place(BLOCK, 2000.0)}
        with pytest.warns(UserWarning, match="1 stop"):
            network = integrate(transit_from(trips, positions), street())
        far = stop_node(network, "FAR")
        connectors = network.edges_df[network.edges_df["edge_type"] == "connector"]
        assert far not in set(connectors["from"]) | set(connectors["to"])
        assert network.metadata["stranded_stops"] == 1
        # The trip still passes through it: 1 + 10 + 2 + 1 + 0 + 1.
        assert cost(network, WEST, EAST) == pytest.approx(15.0, abs=0.01)

    def test_max_connector_dist_is_respected(self, transit_from) -> None:
        with pytest.warns(UserWarning, match="2 stop"), pytest.raises(NetworkIntegrationError):
            integrate(transit_from(EVERY_TWENTY), street(), max_connector_dist=50.0)

    def test_network_with_no_connections_is_refused(self, transit_from) -> None:
        positions = {"A": place(0, 5000.0), "B": place(BLOCK, 5000.0)}
        with pytest.warns(UserWarning), pytest.raises(NetworkIntegrationError, match="connect"):
            integrate(transit_from(EVERY_TWENTY, positions), street())


class TestReturnedNetwork:
    def test_is_a_pandarm_network_with_one_impedance(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        assert isinstance(network, pandarm.Network)
        assert network.impedance_names == ["minutes"]

    def test_edges_are_labelled(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        edges = network.edges_df
        assert set(edges["edge_type"]) == {"walk", "ride", "board", "alight", "connector"}
        ride = edges[edges["edge_type"] == "ride"]
        assert ride["route_id"].tolist() == ["feed_0_R"]
        assert edges.loc[edges["edge_type"] == "walk", "route_id"].isna().all()

    def test_nodes_are_labelled(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        nodes = network.nodes_df
        assert nodes["node_type"].value_counts().to_dict() == {
            "pedestrian": 3,
            "stop": 2,
            "route_stop": 2,
        }
        at_a = nodes[(nodes["stop_id"] == "feed_0_A") & (nodes["node_type"] == "route_stop")]
        assert at_a["route_id"].tolist() == ["feed_0_R"]
        assert at_a["feed"].tolist() == ["feed_0"]

    def test_metadata_records_the_inputs(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street(), walk_speed_mph=3.5)
        metadata = network.metadata
        assert metadata["feeds"][0]["prefix"] == "feed_0"
        assert metadata["feeds"][0]["service_date"] == MONDAY
        assert metadata["time_window"] == list(AM)
        assert metadata["walk_speed_mph"] == 3.5
        assert metadata["max_connector_dist"] == 800.0
        assert metadata["stranded_stops"] == 0
        assert metadata["pedestrian"]["impedance"] == "length"
        assert metadata["pedestrian"]["unit"] == "meters"
        assert isinstance(metadata["netweave_version"], str)

    def test_metadata_is_json_compatible(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        assert json.loads(json.dumps(network.metadata)) == network.metadata


class TestSnapping:
    def test_a_point_beside_a_stop_snaps_to_a_pedestrian_node(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        beside = network.nodes_df.loc[stop_node(network, "A")]
        node = network.get_node_ids(pd.Series([beside["x"] + 1.0]), pd.Series([beside["y"]]))
        assert node.tolist() == [WEST]

    def test_points_of_interest_snap_to_pedestrian_nodes(self, transit_from) -> None:
        network = integrate(transit_from(EVERY_TWENTY), street())
        # Not beside stop A: pandarm 0.0.5 aborts when a point snaps to the node at position 0.
        beside = network.nodes_df.loc[stop_node(network, "B")]
        network.set_pois("shop", 60, 1, pd.Series([beside["x"] + 1.0]), pd.Series([beside["y"]]))
        found = network.nearest_pois(60, "shop", num_pois=1, imp_name="minutes")
        assert found.loc[EAST, 1] == pytest.approx(0.0, abs=0.01)
        # 1 walk + 10 wait + 3 ride + 0 alight + 1 walk.
        assert found.loc[WEST, 1] == pytest.approx(15.0, abs=0.01)
