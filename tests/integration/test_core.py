"""Tests for network integration."""


import numpy as np
import pandas as pd
import pandarm
import pytest

from netweave.exceptions import EmptyNetworkError, NetworkIntegrationError
from netweave.integration.core import integrate
from netweave.types import OSMNetwork, TransitNetwork


class TestIntegrate:
    def test_basic_integration(self) -> None:
        transit_nodes = pd.DataFrame({
            "node_id": ["S1", "S2"],
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        transit_edges = pd.DataFrame({
            "from": ["S1"],
            "to": ["S2"],
            "weight": [10.0],
        })
        transit = TransitNetwork(edges=transit_edges, nodes=transit_nodes)

        osm_nodes = pd.DataFrame({
            "node_id": ["N1", "N2"],
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        osm_edges = pd.DataFrame({
            "from": ["N1"],
            "to": ["N2"],
            "weight": [5.0],
        })
        osm = OSMNetwork(edges=osm_edges, nodes=osm_nodes)

        integrated = integrate(transit, osm, max_connector_dist=1000)
        assert len(integrated.nodes) == 4
        assert len(integrated.edges) == 6  # 1 transit + 1 osm + 4 connectors (bidirectional for 2 stops)
        assert len(integrated.connector_edges) > 0

    def test_empty_transit_raises(self) -> None:
        transit = TransitNetwork(edges=pd.DataFrame(), nodes=pd.DataFrame())
        osm = OSMNetwork(edges=pd.DataFrame({"from": ["N1"], "to": ["N2"], "weight": [1.0]}), nodes=pd.DataFrame({"node_id": ["N1"], "x": [0.0], "y": [0.0]}))
        with pytest.raises(EmptyNetworkError):
            integrate(transit, osm)

    def test_max_connector_dist_filter(self) -> None:
        transit_nodes = pd.DataFrame({
            "node_id": ["S1"],
            "x": [-122.0],
            "y": [37.0],
        })
        transit_edges = pd.DataFrame({
            "from": ["S1"],
            "to": ["S1"],
            "weight": [0.0],
        })
        transit = TransitNetwork(edges=transit_edges, nodes=transit_nodes)

        osm_nodes = pd.DataFrame({
            "node_id": ["N1"],
            "x": [-123.0],  # Far away
            "y": [38.0],
        })
        osm_edges = pd.DataFrame({
            "from": ["N1"],
            "to": ["N1"],
            "weight": [0.0],
        })
        osm = OSMNetwork(edges=osm_edges, nodes=osm_nodes)

        integrated = integrate(transit, osm, max_connector_dist=100)
        assert integrated.connector_edges.empty

    def test_pandarm_network_accepted(self) -> None:
        """Test that integrate() accepts a pandarm.Network directly."""
        transit_nodes = pd.DataFrame({
            "node_id": ["S1", "S2"],
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        transit_edges = pd.DataFrame({
            "from": ["S1"],
            "to": ["S2"],
            "weight": [10.0],
        })
        transit = TransitNetwork(edges=transit_edges, nodes=transit_nodes)

        # Build an equivalent pandarm.Network from the same data
        osm_nodes = pd.DataFrame({
            "node_id": ["N1", "N2"],
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        }).set_index("node_id")
        osm_edges = pd.DataFrame({
            "from": ["N1"],
            "to": ["N2"],
            "weight": [5.0],
        })
        pandarm_net = pandarm.Network(
            node_x=osm_nodes["x"],
            node_y=osm_nodes["y"],
            edge_from=osm_edges["from"],
            edge_to=osm_edges["to"],
            edge_weights=osm_edges[["weight"]],
        )

        integrated = integrate(transit, pandarm_net, max_connector_dist=1000)
        assert len(integrated.nodes) == 4
        assert len(integrated.edges) == 6
        assert len(integrated.connector_edges) > 0

    def test_invalid_osm_type_raises(self) -> None:
        """Test that an invalid type for osm raises TypeError."""
        transit_nodes = pd.DataFrame({
            "node_id": ["S1"],
            "x": [-122.0],
            "y": [37.0],
        })
        transit_edges = pd.DataFrame({
            "from": ["S1"],
            "to": ["S1"],
            "weight": [0.0],
        })
        transit = TransitNetwork(edges=transit_edges, nodes=transit_nodes)

        with pytest.raises(TypeError):
            integrate(transit, "not a network")

    def test_pandarm_named_index_creates_node_id(self) -> None:
        """Test that _pandarm_to_osm_network handles named indices (e.g. 'osmid')."""
        from netweave.integration.core import _pandarm_to_osm_network

        # Build a pandarm.Network whose nodes_df has a named index ("osmid")
        osm_nodes = pd.DataFrame({
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        }, index=pd.Index([100, 200], name="osmid"))
        osm_edges = pd.DataFrame({
            "from": [100],
            "to": [200],
            "weight": [5.0],
        })
        pandarm_net = pandarm.Network(
            node_x=osm_nodes["x"],
            node_y=osm_nodes["y"],
            edge_from=osm_edges["from"],
            edge_to=osm_edges["to"],
            edge_weights=osm_edges[["weight"]],
        )

        result = _pandarm_to_osm_network(pandarm_net)

        # The result must have a 'node_id' column (not 'osmid' or 'index')
        assert "node_id" in result.nodes.columns
        # The node_id values should match the original osmid values
        assert set(result.nodes["node_id"]) == {100, 200}
        # The edges should reference the same node IDs
        assert set(result.edges["from"]) == {100}
        assert set(result.edges["to"]) == {200}

    def test_pandarm_unnamed_index_creates_node_id(self) -> None:
        """Test that _pandarm_to_osm_network handles unnamed indices."""
        from netweave.integration.core import _pandarm_to_osm_network

        # Build a pandarm.Network whose nodes_df has an unnamed integer index
        osm_nodes = pd.DataFrame({
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        osm_edges = pd.DataFrame({
            "from": [0],
            "to": [1],
            "weight": [5.0],
        })
        pandarm_net = pandarm.Network(
            node_x=osm_nodes["x"],
            node_y=osm_nodes["y"],
            edge_from=osm_edges["from"],
            edge_to=osm_edges["to"],
            edge_weights=osm_edges[["weight"]],
        )

        result = _pandarm_to_osm_network(pandarm_net)

        # The result must have a 'node_id' column
        assert "node_id" in result.nodes.columns
        # The node_id values should match the original index values
        assert len(result.nodes) == 2

    def test_pandarm_weight_conversion(self) -> None:
        """Test that pandarm meter-based weights are converted to minutes."""
        from netweave.integration.core import _pandarm_to_osm_network

        # Build a pandarm.Network with meter-based weights (typical of from_gdf)
        osm_nodes = pd.DataFrame({
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        osm_edges = pd.DataFrame({
            "from": [0],
            "to": [1],
            "weight": [100.0],  # 100 meters
            "length": [100.0],   # length column signals meter-based weights
        })
        pandarm_net = pandarm.Network(
            node_x=osm_nodes["x"],
            node_y=osm_nodes["y"],
            edge_from=osm_edges["from"],
            edge_to=osm_edges["to"],
            edge_weights=osm_edges[["weight"]],
        )

        result = _pandarm_to_osm_network(pandarm_net)

        # Weight should be converted from meters to minutes
        # 100 meters = 0.0621 miles, at 3 mph = 1.24 minutes
        original_meters = 100.0
        expected_minutes = (original_meters / 1609.344) / 3.0 * 60.0
        assert abs(result.edges["weight"].iloc[0] - expected_minutes) < 0.01
        # Should NOT still be 100
        assert result.edges["weight"].iloc[0] < 10

    def test_pandarm_minute_weights_preserved(self) -> None:
        """Test that pandarm weights already in minutes are not double-converted."""
        from netweave.integration.core import _pandarm_to_osm_network

        # Build a pandarm.Network with minute-based weights (no length column)
        osm_nodes = pd.DataFrame({
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        osm_edges = pd.DataFrame({
            "from": [0],
            "to": [1],
            "weight": [2.5],  # 2.5 minutes (already converted)
        })
        pandarm_net = pandarm.Network(
            node_x=osm_nodes["x"],
            node_y=osm_nodes["y"],
            edge_from=osm_edges["from"],
            edge_to=osm_edges["to"],
            edge_weights=osm_edges[["weight"]],
        )

        result = _pandarm_to_osm_network(pandarm_net)

        # Weight should NOT be converted (mean < 10, no length column)
        assert abs(result.edges["weight"].iloc[0] - 2.5) < 0.01

    def test_weight_unit_meters(self) -> None:
        """Test weight_unit='meters' always converts regardless of mean."""
        from netweave.integration.core import _pandarm_to_osm_network

        osm_nodes = pd.DataFrame({
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        # Even with small values that look like minutes, meters should convert
        osm_edges = pd.DataFrame({
            "from": [0],
            "to": [1],
            "weight": [5.0],  # 5 meters (small, looks like minutes)
        })
        pandarm_net = pandarm.Network(
            node_x=osm_nodes["x"],
            node_y=osm_nodes["y"],
            edge_from=osm_edges["from"],
            edge_to=osm_edges["to"],
            edge_weights=osm_edges[["weight"]],
        )

        result = _pandarm_to_osm_network(pandarm_net, weight_unit="meters")

        # 5 meters should be converted to minutes
        expected = (5.0 / 1609.344) / 3.0 * 60.0
        assert abs(result.edges["weight"].iloc[0] - expected) < 0.01

    def test_weight_unit_minutes(self) -> None:
        """Test weight_unit='minutes' never converts even with large values."""
        from netweave.integration.core import _pandarm_to_osm_network

        osm_nodes = pd.DataFrame({
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        # Large values that look like meters, but are actually minutes
        osm_edges = pd.DataFrame({
            "from": [0],
            "to": [1],
            "weight": [45.0],  # 45 minutes (large, looks like meters)
        })
        pandarm_net = pandarm.Network(
            node_x=osm_nodes["x"],
            node_y=osm_nodes["y"],
            edge_from=osm_edges["from"],
            edge_to=osm_edges["to"],
            edge_weights=osm_edges[["weight"]],
        )

        result = _pandarm_to_osm_network(pandarm_net, weight_unit="minutes")

        # Should NOT be converted — weight_unit='minutes' means already in minutes
        assert abs(result.edges["weight"].iloc[0] - 45.0) < 0.01

    def test_weight_unit_seconds(self) -> None:
        """Test weight_unit='seconds' converts seconds to minutes."""
        from netweave.integration.core import _pandarm_to_osm_network

        osm_nodes = pd.DataFrame({
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        osm_edges = pd.DataFrame({
            "from": [0],
            "to": [1],
            "weight": [300.0],  # 300 seconds = 5 minutes
        })
        pandarm_net = pandarm.Network(
            node_x=osm_nodes["x"],
            node_y=osm_nodes["y"],
            edge_from=osm_edges["from"],
            edge_to=osm_edges["to"],
            edge_weights=osm_edges[["weight"]],
        )

        result = _pandarm_to_osm_network(pandarm_net, weight_unit="seconds")

        # 300 seconds should become 5 minutes
        assert abs(result.edges["weight"].iloc[0] - 5.0) < 0.01

    def test_weight_unit_auto_with_impedance_length(self) -> None:
        """Test weight_unit='auto' detects meters via impedance_names='length'."""
        from netweave.integration.core import _pandarm_to_osm_network

        osm_nodes = pd.DataFrame({
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        # Small values (mean < 10) but impedance is 'length' → should convert.
        # We create the Network with 'length' as the impedance column name.
        osm_edges = pd.DataFrame({
            "from": [0],
            "to": [1],
            "length": [5.0],  # 5 meters, named 'length' like from_gdf
        })
        pandarm_net = pandarm.Network(
            node_x=osm_nodes["x"],
            node_y=osm_nodes["y"],
            edge_from=osm_edges["from"],
            edge_to=osm_edges["to"],
            edge_weights=osm_edges[["length"]],
        )

        result = _pandarm_to_osm_network(pandarm_net, weight_unit="auto")

        # Should be converted because impedance_names[0] == "length"
        expected = (5.0 / 1609.344) / 3.0 * 60.0
        assert abs(result.edges["weight"].iloc[0] - expected) < 0.01

    def test_weight_unit_invalid_raises(self) -> None:
        """Test that invalid weight_unit raises ValueError."""
        from netweave.integration.core import _pandarm_to_osm_network

        osm_nodes = pd.DataFrame({
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        osm_edges = pd.DataFrame({
            "from": [0],
            "to": [1],
            "weight": [100.0],
        })
        pandarm_net = pandarm.Network(
            node_x=osm_nodes["x"],
            node_y=osm_nodes["y"],
            edge_from=osm_edges["from"],
            edge_to=osm_edges["to"],
            edge_weights=osm_edges[["weight"]],
        )

        with pytest.raises(ValueError, match="weight_unit"):
            _pandarm_to_osm_network(pandarm_net, weight_unit="invalid")

    def test_negative_weights_dropped(self) -> None:
        """Test that negative-weight edges are dropped during integration."""
        transit_nodes = pd.DataFrame({
            "node_id": ["S1", "S2"],
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        # Include a negative-weight edge (data error)
        transit_edges = pd.DataFrame({
            "from": ["S1", "S1"],
            "to": ["S2", "S2"],
            "weight": [10.0, -5.0],
        })
        transit = TransitNetwork(edges=transit_edges, nodes=transit_nodes)

        osm_nodes = pd.DataFrame({
            "node_id": ["N1", "N2"],
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        osm_edges = pd.DataFrame({
            "from": ["N1"],
            "to": ["N2"],
            "weight": [5.0],
        })
        osm = OSMNetwork(edges=osm_edges, nodes=osm_nodes)

        integrated = integrate(transit, osm, max_connector_dist=1000)
        # Negative-weight edge should be dropped
        assert (integrated.edges["weight"] < 0).sum() == 0
        # The valid transit edge should still be present
        assert (integrated.edges["weight"] == 10.0).sum() >= 1
