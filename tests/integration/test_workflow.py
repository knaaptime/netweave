"""End-to-end test: two feeds on disk, through to a query in pandarm."""

import zipfile

import geopandas as gpd
import pandarm
import pandas as pd
import pytest
from helpers import schedule
from shapely.geometry import Point

import netweave as nw

UTM = 32610
X0, Y0 = 550_000.0, 4_180_000.0
MINUTE = 80.4672
AM = ("07:00:00", "10:00:00")


def lonlat(x_offset, y_offset):
    point = gpd.GeoSeries([Point(X0 + x_offset, Y0 + y_offset)], crs=UTM).to_crs(4326).iloc[0]
    return f"{point.x:.9f}", f"{point.y:.9f}"


def zipped(folder, destination):
    with zipfile.ZipFile(destination, "w") as archive:
        for path in folder.iterdir():
            archive.write(path, path.name)
    return destination


def test_a_trip_across_two_agencies(write_feed, tmp_path) -> None:
    # Both feeds call their route "R" and their stops "1" and "2", and their
    # validity does not overlap, so each must choose its own Monday.
    bus = schedule(
        {
            "t": ("R", None, [("1", "08:00:00"), ("2", "08:04:00")]),
            "u": ("R", None, [("1", "08:10:00"), ("2", "08:14:00")]),
        }
    )
    rail = schedule(
        {
            "t": ("R", None, [("1", "08:05:00"), ("2", "08:11:00")]),
            "u": ("R", None, [("1", "08:25:00"), ("2", "08:31:00")]),
        }
    )
    rail["calendar"]["start_date"], rail["calendar"]["end_date"] = ["20260701"], ["20261231"]
    # The bus runs along the street to the 1000 m mark, where the rail line starts.
    bus["stops"]["stop_lon"], bus["stops"]["stop_lat"] = zip(
        lonlat(0, 0), lonlat(1000, 0), strict=True
    )
    rail["stops"]["stop_lon"], rail["stops"]["stop_lat"] = zip(
        lonlat(1000, 0), lonlat(2000, 0), strict=True
    )

    feeds = [
        nw.load_feed(zipped(write_feed(bus, name="bus"), tmp_path / "bus.zip")),
        nw.load_feed(zipped(write_feed(rail, name="rail"), tmp_path / "rail.zip")),
    ]
    feeds[0].onestop_id, feeds[1].onestop_id = "f-bus", "f-rail"
    transit = nw.create_transit_network(feeds, day="monday", timerange=AM)

    ids = [10, 11, 12]
    pedestrian = pandarm.Network(
        pd.Series([X0, X0 + 1000.0, X0 + 2000.0], index=ids),
        pd.Series([Y0, Y0, Y0], index=ids),
        pd.Series([10, 11, 11, 12]),
        pd.Series([11, 10, 12, 11]),
        pd.DataFrame({"length": [3000.0] * 4}),
        twoway=False,
        crs=UTM,
    )
    network = nw.integrate(transit, pedestrian)

    assert isinstance(network, pandarm.Network)
    assert [(feed["prefix"], feed["service_date"]) for feed in network.metadata["feeds"]] == [
        ("f-bus", "20260105"),
        ("f-rail", "20260706"),
    ]
    # Bus: wait 5, ride 4. Change agencies through the pedestrian node both stops sit on,
    # at no distance. Rail: wait 10, ride 6. Walking either block would take over 37 minutes.
    assert network.shortest_path_length(10, 11, imp_name="minutes") == pytest.approx(9.0, abs=0.01)
    assert network.shortest_path_length(10, 12, imp_name="minutes") == pytest.approx(25.0, abs=0.01)


def test_a_saved_network_reloads_with_the_same_costs(write_feed, tmp_path) -> None:
    tables = schedule(
        {
            "t": ("R", None, [("1", "08:00:00"), ("2", "08:04:00")]),
            "u": ("R", None, [("1", "08:10:00"), ("2", "08:14:00")]),
        }
    )
    tables["stops"]["stop_lon"], tables["stops"]["stop_lat"] = zip(
        lonlat(0, 0), lonlat(1000, 0), strict=True
    )
    transit = nw.create_transit_network(
        nw.load_feed(write_feed(tables)), date="20260105", timerange=AM
    )
    ids = [10, 11]
    pedestrian = pandarm.Network(
        pd.Series([X0, X0 + 1000.0], index=ids),
        pd.Series([Y0, Y0], index=ids),
        pd.Series([10, 11]),
        pd.Series([11, 10]),
        pd.DataFrame({"length": [1000.0, 1000.0]}),
        twoway=False,
        crs=UTM,
    )
    network = nw.integrate(transit, pedestrian)
    path = tmp_path / "network.h5"
    network.save_hdf5(str(path))
    reloaded = pandarm.Network.from_hdf5(str(path))
    assert reloaded.impedance_names == ["minutes"]
    assert reloaded.shortest_path_length(10, 11, imp_name="minutes") == pytest.approx(
        network.shortest_path_length(10, 11, imp_name="minutes"), abs=0.001
    )
