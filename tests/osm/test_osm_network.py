"""Tests for OSM network processing."""


import pandas as pd
import pytest

from netweave.osm.network import create_osm_network
from netweave.types import OSMNetwork


class TestCreateOSMNetwork:
    def test_weight_computation(self) -> None:
        nodes = pd.DataFrame({
            "node_id": ["N1", "N2"],
            "x": [-122.0, -122.1],
            "y": [37.0, 37.1],
        })
        edges = pd.DataFrame({
            "u": ["N1"],
            "v": ["N2"],
            "length": [1609.344],  # 1 mile in meters
        })
        osm = OSMNetwork(edges=edges, nodes=nodes)
        result = create_osm_network(osm, walk_speed_mph=3.0)
        # 1 mile at 3 mph = 20 minutes
        assert result.edges.iloc[0]["weight"] == pytest.approx(20.0, rel=1e-3)

    def test_missing_length_raises(self) -> None:
        nodes = pd.DataFrame({
            "node_id": ["N1"],
            "x": [-122.0],
            "y": [37.0],
        })
        edges = pd.DataFrame({
            "u": ["N1"],
            "v": ["N1"],
        })
        osm = OSMNetwork(edges=edges, nodes=nodes)
        with pytest.raises(ValueError):
            create_osm_network(osm)
