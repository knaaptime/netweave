"""Tests for GTFS transit network generation."""


import geopandas as gpd
import pytest
from shapely.geometry import LineString

from netweave.exceptions import EmptyNetworkError
from netweave.gtfs.network import (
    _assign_shape_to_edges,
    _build_shape_geometries,
    _build_stop_geometries,
    create_transit_network,
)


class TestCreateTransitNetwork:
    def test_basic_network(self, minimal_gtfs_feed) -> None:
        transit = create_transit_network(
            minimal_gtfs_feed,
            day="monday",
            timerange=("07:00:00", "10:00:00"),
        )
        assert len(transit.nodes) == 3
        assert len(transit.edges) == 4  # 2 trips * 2 edges each
        assert "weight" in transit.edges.columns
        assert "net_type" in transit.edges.columns
        # Edges should be a GeoDataFrame with geometry column
        assert isinstance(transit.edges, gpd.GeoDataFrame)
        assert transit.edges.crs.to_string() == "EPSG:4326"
        assert "geometry" in transit.edges.columns

    def test_empty_timerange_raises(self, minimal_gtfs_feed) -> None:
        with pytest.raises(EmptyNetworkError):
            create_transit_network(
                minimal_gtfs_feed,
                day="monday",
                timerange=("10:00:00", "11:00:00"),
            )

    def test_simplify(self, minimal_gtfs_feed) -> None:
        transit = create_transit_network(
            minimal_gtfs_feed,
            day="monday",
            timerange=("07:00:00", "10:00:00"),
            simplify=True,
        )
        # Simplification should reduce duplicate edges
        assert len(transit.edges) <= 4

    def test_invalid_day_raises(self, minimal_gtfs_feed) -> None:
        with pytest.raises(ValueError):
            create_transit_network(
                minimal_gtfs_feed,
                day="invalid_day",
            )

    def test_prune_by_bbox(self, minimal_gtfs_feed) -> None:
        """Prune to bbox should keep only stops inside the area."""
        # The minimal feed has stops at lat/lon around 37.0, -122.0
        # Prune to a bbox that only includes one stop
        transit = create_transit_network(
            minimal_gtfs_feed,
            day="monday",
            timerange=("07:00:00", "10:00:00"),
            prune=(-122.5, 36.5, -121.5, 37.5),  # bbox around the stops
        )
        # All 3 stops should be inside this large bbox
        assert len(transit.nodes) == 3

        # Now prune to a very small bbox that excludes all stops
        with pytest.raises(EmptyNetworkError):
            create_transit_network(
                minimal_gtfs_feed,
                day="monday",
                timerange=("07:00:00", "10:00:00"),
                prune=(-100.0, 20.0, -90.0, 30.0),  # bbox far away
            )

    def test_prune_empty_raises(self, minimal_gtfs_feed) -> None:
        """Prune to empty area should raise EmptyNetworkError."""
        with pytest.raises(EmptyNetworkError):
            create_transit_network(
                minimal_gtfs_feed,
                day="monday",
                timerange=("07:00:00", "10:00:00"),
                prune=(-100.0, 20.0, -90.0, 30.0),  # bbox far away
            )


class TestGeometry:
    """Tests for geometry generation in transit networks."""

    def test_geometry_fallback_without_shapes(self, minimal_gtfs_feed) -> None:
        """When no shapes.txt, edges should have straight-line geometries."""
        transit = create_transit_network(
            minimal_gtfs_feed,
            day="monday",
            timerange=("07:00:00", "10:00:00"),
        )
        assert "geometry" in transit.edges.columns
        assert isinstance(transit.edges, gpd.GeoDataFrame)
        assert transit.edges.crs.to_string() == "EPSG:4326"
        # All geometries should be LineStrings
        for geom in transit.edges["geometry"]:
            assert isinstance(geom, LineString)
        # Each edge should connect two stops (2-point LineString)
        for geom in transit.edges["geometry"]:
            assert len(geom.coords) == 2

    def test_geometry_with_shapes(self, gtfs_feed_with_shapes) -> None:
        """When shapes.txt is present, edges should use shape geometries."""
        transit = create_transit_network(
            gtfs_feed_with_shapes,
            day="monday",
            timerange=("07:00:00", "10:00:00"),
        )
        assert "geometry" in transit.edges.columns
        assert isinstance(transit.edges, gpd.GeoDataFrame)
        assert transit.edges.crs.to_string() == "EPSG:4326"
        # All geometries should be LineStrings
        for geom in transit.edges["geometry"]:
            assert isinstance(geom, LineString)

    def test_geometry_survives_simplification(self, minimal_gtfs_feed) -> None:
        """Geometry column should survive network simplification."""
        transit = create_transit_network(
            minimal_gtfs_feed,
            day="monday",
            timerange=("07:00:00", "10:00:00"),
            simplify=True,
        )
        assert "geometry" in transit.edges.columns
        assert isinstance(transit.edges, gpd.GeoDataFrame)
        assert transit.edges.crs.to_string() == "EPSG:4326"
        for geom in transit.edges["geometry"]:
            assert isinstance(geom, LineString)

    def test_stop_geometry_coordinates(self, minimal_gtfs_feed) -> None:
        """Stop-to-stop geometries should use correct stop coordinates."""
        transit = create_transit_network(
            minimal_gtfs_feed,
            day="monday",
            timerange=("07:00:00", "10:00:00"),
        )
        nodes = transit.nodes.set_index("node_id")
        for _, row in transit.edges.iterrows():
            geom = row["geometry"]
            from_node = nodes.loc[row["from"]]
            to_node = nodes.loc[row["to"]]
            # Check that geometry starts at from-node and ends at to-node
            assert abs(geom.coords[0][0] - float(from_node["x"])) < 1e-6
            assert abs(geom.coords[0][1] - float(from_node["y"])) < 1e-6
            assert abs(geom.coords[-1][0] - float(to_node["x"])) < 1e-6
            assert abs(geom.coords[-1][1] - float(to_node["y"])) < 1e-6


class TestBuildShapeGeometries:
    """Tests for _build_shape_geometries helper."""

    def test_basic_shapes(self) -> None:
        import pandas as pd

        shapes = pd.DataFrame({
            "shape_id": ["SH1", "SH1", "SH1"],
            "shape_pt_lat": [37.0, 37.1, 37.2],
            "shape_pt_lon": [-122.0, -122.1, -122.2],
            "shape_pt_sequence": [1, 2, 3],
        })
        result = _build_shape_geometries(shapes)
        assert isinstance(result, gpd.GeoDataFrame)
        assert result.crs.to_string() == "EPSG:4326"
        assert len(result) == 1
        assert result.iloc[0]["shape_id"] == "SH1"
        geom = result.iloc[0]["geometry"]
        assert isinstance(geom, LineString)
        assert len(geom.coords) == 3

    def test_empty_shapes(self) -> None:
        import pandas as pd

        shapes = pd.DataFrame(columns=["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"])
        result = _build_shape_geometries(shapes)
        assert isinstance(result, gpd.GeoDataFrame)
        assert result.crs.to_string() == "EPSG:4326"
        assert result.empty

    def test_multiple_shapes(self) -> None:
        import pandas as pd

        shapes = pd.DataFrame({
            "shape_id": ["SH1", "SH1", "SH2", "SH2"],
            "shape_pt_lat": [37.0, 37.1, 38.0, 38.1],
            "shape_pt_lon": [-122.0, -122.1, -123.0, -123.1],
            "shape_pt_sequence": [1, 2, 1, 2],
        })
        result = _build_shape_geometries(shapes)
        assert isinstance(result, gpd.GeoDataFrame)
        assert result.crs.to_string() == "EPSG:4326"
        assert len(result) == 2


class TestBuildStopGeometries:
    """Tests for _build_stop_geometries helper."""

    def test_basic_stop_geometries(self) -> None:
        import pandas as pd

        edges = pd.DataFrame({"from": [1, 2], "to": [2, 3]})
        nodes = pd.DataFrame({
            "node_id": [1, 2, 3],
            "x": [-122.0, -122.1, -122.2],
            "y": [37.0, 37.1, 37.2],
        })
        result = _build_stop_geometries(edges, nodes)
        assert isinstance(result, gpd.GeoSeries)
        assert result.crs.to_string() == "EPSG:4326"
        assert len(result) == 2
        for geom in result:
            assert isinstance(geom, LineString)
            assert len(geom.coords) == 2
