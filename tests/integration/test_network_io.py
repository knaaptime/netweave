"""Tests for network I/O."""


import tempfile
from pathlib import Path

import pandas as pd
import pytest

from netweave.integration._io import load_network, save_network
from netweave.types import IntegratedNetwork


class TestSaveLoadNetwork:
    def test_geoparquet_roundtrip(self) -> None:
        pytest.importorskip("pyarrow")
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
        with tempfile.TemporaryDirectory() as tmpdir:
            save_network(network, tmpdir, format="geoparquet")
            loaded = load_network(tmpdir, format="geoparquet")
            assert len(loaded.nodes) == len(network.nodes)
            assert len(loaded.edges) == len(network.edges)

    def test_hdf5_roundtrip(self) -> None:
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
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "network.h5"
            save_network(network, path, format="hdf5")
            loaded = load_network(path, format="hdf5")
            assert len(loaded.nodes) == len(network.nodes)
            assert len(loaded.edges) == len(network.edges)
