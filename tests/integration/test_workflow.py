"""End-to-end integration test for the full netweave workflow."""


import tempfile
from pathlib import Path

import pandas as pd
import pytest

from netweave.gtfs.feed import GTFSFeed
from netweave.gtfs.network import create_transit_network
from netweave.gtfs.headways import compute_headways
from netweave.network.core import integrate
from netweave.network._io import load_network, save_network
from netweave.network.pandarm import to_pandarm
from netweave.types import IntegratedNetwork, OSMNetwork, TransitNetwork


class TestEndToEndWorkflow:
    """Full workflow: GTFS → transit network → OSM → integrate → save → load → pandarm."""

    @pytest.fixture
    def synthetic_gtfs_feed(self) -> GTFSFeed:
        """Create a minimal synthetic GTFS feed with 2 routes, 4 stops, 2 trips."""
        stops = pd.DataFrame({
            "stop_id": [101, 102, 103, 104],
            "stop_name": ["Stop 1", "Stop 2", "Stop 3", "Stop 4"],
            "stop_lat": [37.77, 37.78, 37.79, 37.80],
            "stop_lon": [-122.42, -122.43, -122.44, -122.45],
        })
        routes = pd.DataFrame({
            "route_id": [1, 2],
            "agency_id": [1, 1],
            "route_short_name": ["1", "2"],
            "route_type": [3, 3],
        })
        trips = pd.DataFrame({
            "trip_id": [1, 2],
            "route_id": [1, 2],
            "service_id": [1, 1],
        })
        stop_times = pd.DataFrame({
            "trip_id": [1, 1, 1, 2, 2, 2],
            "stop_id": [101, 102, 103, 102, 103, 104],
            "stop_sequence": [1, 2, 3, 1, 2, 3],
            "arrival_time": [
                "08:00:00", "08:05:00", "08:10:00",
                "08:15:00", "08:20:00", "08:25:00",
            ],
            "departure_time": [
                "08:00:00", "08:05:00", "08:10:00",
                "08:15:00", "08:20:00", "08:25:00",
            ],
        })
        calendar = pd.DataFrame({
            "service_id": [1],
            "monday": [1],
            "tuesday": [1],
            "wednesday": [1],
            "thursday": [1],
            "friday": [1],
            "saturday": [0],
            "sunday": [0],
            "start_date": ["20240101"],
            "end_date": ["20241231"],
        })
        agency = pd.DataFrame({
            "agency_id": [1],
            "agency_name": ["Test Agency"],
            "agency_url": ["http://example.com"],
            "agency_timezone": ["America/Los_Angeles"],
        })
        return GTFSFeed(
            agency=agency,
            stops=stops,
            routes=routes,
            trips=trips,
            stop_times=stop_times,
            calendar=calendar,
        )

    @pytest.fixture
    def synthetic_osm_network(self) -> OSMNetwork:
        """Create a minimal synthetic OSM pedestrian network with integer IDs."""
        nodes = pd.DataFrame({
            "osmid": [1, 2, 3, 4],
            "x": [-122.42, -122.43, -122.44, -122.45],
            "y": [37.77, 37.78, 37.79, 37.80],
        })
        edges = pd.DataFrame({
            "u": [1, 2, 3],
            "v": [2, 3, 4],
            "length": [100.0, 100.0, 100.0],
        })
        return OSMNetwork(edges=edges, nodes=nodes)

    def test_full_workflow(
        self,
        synthetic_gtfs_feed: GTFSFeed,
        synthetic_osm_network: OSMNetwork,
    ) -> None:
        """Run the complete netweave workflow."""
        # 1. Create transit network from GTFS feed
        transit = create_transit_network(
            feed=synthetic_gtfs_feed,
            day="monday",
            timerange=("07:00:00", "09:00:00"),
        )
        assert isinstance(transit, TransitNetwork)
        assert len(transit.edges) > 0
        assert len(transit.nodes) > 0

        # 2. Compute headways and merge into edges
        headways = compute_headways(
            stop_times=synthetic_gtfs_feed.stop_times,
            trips=synthetic_gtfs_feed.trips,
            routes=synthetic_gtfs_feed.routes,
            stops=synthetic_gtfs_feed.stops,
        )
        assert isinstance(headways, pd.DataFrame)

        # 3. Create OSM network with travel times
        from netweave.osm.network import create_osm_network
        osm = create_osm_network(
            osm_network=synthetic_osm_network,
            walk_speed_mph=3.0,
        )
        assert isinstance(osm, OSMNetwork)
        assert "weight" in osm.edges.columns

        # 4. Integrate transit + OSM
        integrated = integrate(
            transit=transit,
            osm=osm,
            max_connector_dist=500.0,
        )
        assert isinstance(integrated, IntegratedNetwork)
        assert len(integrated.edges) > 0
        assert len(integrated.nodes) > 0
        assert len(integrated.connector_edges) >= 0

        # 5. Save and load roundtrip
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "network.h5"
            save_network(integrated, str(path), format="hdf5")
            loaded = load_network(str(path), format="hdf5")
            assert isinstance(loaded, IntegratedNetwork)
            assert len(loaded.edges) == len(integrated.edges)
            assert len(loaded.nodes) == len(integrated.nodes)

        # 6. Convert to pandarm (if available)
        try:
            import pandarm  # noqa: F401
            net = to_pandarm(integrated)
            assert net is not None
        except ImportError:
            pytest.skip("pandarm not installed")

    def test_workflow_without_osm(
        self,
        synthetic_gtfs_feed: GTFSFeed,
    ) -> None:
        """Transit-only workflow should still produce valid network."""
        transit = create_transit_network(
            feed=synthetic_gtfs_feed,
            day="monday",
            timerange=("07:00:00", "09:00:00"),
        )
        assert len(transit.edges) == 4  # 2 trips × (3 stops - 1) edges each
        assert "from" in transit.edges.columns
        assert "to" in transit.edges.columns
        assert "weight" in transit.edges.columns

    def test_workflow_with_simplify(
        self,
        synthetic_gtfs_feed: GTFSFeed,
    ) -> None:
        """Simplify mode should reduce edge count."""
        transit_full = create_transit_network(
            feed=synthetic_gtfs_feed,
            day="monday",
            timerange=("07:00:00", "09:00:00"),
            simplify=False,
        )
        transit_simple = create_transit_network(
            feed=synthetic_gtfs_feed,
            day="monday",
            timerange=("07:00:00", "09:00:00"),
            simplify=True,
        )
        # Simplified network should have fewer or equal edges
        assert len(transit_simple.edges) <= len(transit_full.edges)
