"""Tests for pandarm bridge."""


import pandas as pd
import pytest

from netweave.integration.pandarm import format_for_pandarm, to_pandarm
from netweave.types import IntegratedNetwork


class TestToPandarm:
    def test_basic_conversion(self) -> None:
        nodes = pd.DataFrame({
            "node_id": ["N1", "N2"],
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        edges = pd.DataFrame({
            "from": ["N1"],
            "to": ["N2"],
            "weight": [10.0],
        })
        connectors = pd.DataFrame({
            "from": ["N1"],
            "to": ["N2"],
            "weight": [5.0],
        })
        network = IntegratedNetwork(
            edges=edges,
            nodes=nodes,
            connector_edges=connectors,
            transit_edges=edges,
            transit_nodes=nodes,
            osm_edges=edges,
            osm_nodes=nodes,
        )
        # This will fail if pandarm is not installed, which is expected in minimal env
        try:
            import pandarm
            result = to_pandarm(network)
            assert result is not None
        except ImportError:
            pytest.skip("pandarm not installed")

    def test_format_for_pandarm(self) -> None:
        nodes = pd.DataFrame({
            "node_id": ["N1", "N2"],
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        edges = pd.DataFrame({
            "from": ["N1"],
            "to": ["N2"],
            "weight": [10.0],
        })
        node_x, node_y, edge_from, edge_to, edge_weights, edge_geom = format_for_pandarm(nodes, edges)
        assert len(node_x) == 2
        assert len(edge_from) == 1
        assert "weight" in edge_weights.columns
        assert edge_geom is None  # No geometry column in edges

    def test_format_for_pandarm_with_geometry(self) -> None:
        from shapely.geometry import LineString

        nodes = pd.DataFrame({
            "node_id": ["N1", "N2"],
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        edges = pd.DataFrame({
            "from": ["N1"],
            "to": ["N2"],
            "weight": [10.0],
            "geometry": [LineString([(-122.0, 37.0), (-122.1, 37.1)])],
        })
        node_x, node_y, edge_from, edge_to, edge_weights, edge_geom = format_for_pandarm(nodes, edges)
        assert edge_geom is not None
        assert len(edge_geom) == 1

    def test_missing_columns_raises(self) -> None:
        nodes = pd.DataFrame({
            "node_id": ["N1"],
        })
        edges = pd.DataFrame({
            "from": ["N1"],
            "to": ["N1"],
        })
        with pytest.raises(ValueError):
            format_for_pandarm(nodes, edges)

    def test_twoway_default_is_false(self) -> None:
        """Test that to_pandarm defaults to twoway=False for integrated networks.

        Integrated networks contain directional transit edges that must
        not get reverse edges, so the default is False.
        """
        nodes = pd.DataFrame({
            "node_id": ["N1", "N2"],
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        edges = pd.DataFrame({
            "from": ["N1"],
            "to": ["N2"],
            "weight": [10.0],
        })
        connectors = pd.DataFrame({
            "from": ["N1"],
            "to": ["N2"],
            "weight": [5.0],
        })
        network = IntegratedNetwork(
            edges=edges,
            nodes=nodes,
            connector_edges=connectors,
            transit_edges=edges,
            transit_nodes=nodes,
            osm_edges=edges,
            osm_nodes=nodes,
        )
        try:
            import pandarm
            result = to_pandarm(network)
            # twoway=False means pandarm does NOT create reverse edges,
            # preserving directional transit edges in integrated networks.
            assert result._twoway is False
        except ImportError:
            pytest.skip("pandarm not installed")
