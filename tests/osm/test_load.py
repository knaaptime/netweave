"""Tests for OSM network loading."""


import pytest

from netweave.osm.load import load_network_from_bbox


class TestLoadNetworkFromBBox:
    @pytest.mark.network
    def test_load_small_bbox(self) -> None:
        # Small bbox around downtown San Francisco
        # bbox format: (left, bottom, right, top) = (min_lon, min_lat, max_lon, max_lat)
        bbox = (-122.42, 37.78, -122.40, 37.80)
        network = load_network_from_bbox(bbox)
        assert len(network.nodes) > 0
        assert len(network.edges) > 0
        assert "node_id" in network.nodes.columns

    def test_load_invalid_bbox(self) -> None:
        # osmnx throws InsufficientResponseError for empty bbox
        bbox = (0.0, 0.0, 0.01, 0.01)
        with pytest.raises(Exception):
            load_network_from_bbox(bbox)
