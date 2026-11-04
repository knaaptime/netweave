# netweave

`netweave` is a package for weaving together GTFS-based transit networks and OSM-based pedestrian networks into an integrated routable multi-modal graph. The result is a [`pandarm`](https://github.com/oturns/pandarm) network with one impedance, travel time in minutes, so that walking, waiting and riding can be compared directly in accessibility analysis.

It is built on

1. the modern scipy stack
2. vectorized computation wherever possible
3. integration with `pandarm` and `geopandas`

`netweave` prepares the network and `pandarm` does the analysis. The package is under active development and has not been released.

## Usage

```python
import geopandas as gpd
import netweave as nw
import pandarm

area = gpd.read_file("study_area.gpkg")
points = gpd.read_file("origins.gpkg").geometry

# Download the pedestrian network from OpenStreetMap
pedestrian = pandarm.Network.from_gdf(area)

# Find, download and merge the GTFS feeds that serve the area
feed = nw.fetch_feeds(polygon=area)

# Build the transit network for a weekday morning
transit = nw.create_transit_network(
    feed, day="monday", timerange=("07:00:00", "10:00:00"), prune=area
)

# Join them into one pandarm.Network
net = nw.integrate(transit, pedestrian)

# Analyze it with pandarm
origins = net.get_node_ids(points.x, points.y)
reachable = net.nodes_in_range(origins, 30, imp_name="minutes")
```

`from_gdf` needs `osmnx`. `fetch_feeds` searches [Transitland](https://www.transit.land) and needs an API key, passed as `api_key` or set as `TRANSITLAND_API_KEY`. To use feeds you already have, read them with `nw.load_feed` and pass one, or a list, to `create_transit_network`.

## What the network contains

A stop is a node, and so is each route at a stop, in each direction where the feed records direction. Five kinds of edge connect them.

| Edge | Joins | Costs |
|---|---|---|
| Walk | pedestrian nodes | walking time |
| Connector | a stop and its nearest pedestrian node, both ways | walking time |
| Boarding | a stop to a route at that stop | half the route's mean headway |
| Ride | consecutive stops on a route | mean scheduled time across trips in the window |
| Alighting | a route back to its stop | nothing |

Changing routes at a stop therefore costs the wait for the next route and no walking. A route with one departure in the window counts the whole window as its headway, and `use_headways=False` removes the wait altogether.

A network represents one time window, so build one for each period you want to compare. Times follow the GTFS clock, where `("24:00:00", "26:00:00")` on a Monday means early on Tuesday.

## Choosing feeds and service

`day="monday"` uses the busiest Monday in each feed, chosen separately because the feeds of different agencies need not be valid at the same time. `date="20260302"` uses that date in every feed. Service exceptions apply in both cases, and `metadata` records the date each feed used.

Merging gives every feed's IDs a prefix from its Onestop ID, so IDs from different agencies cannot collide. A feed that cannot be used, or whose licence does not allow redistribution, is left out with a warning and listed in `feed.missing`.

## Working with the result

`integrate` keeps the IDs of your pedestrian nodes, uses the CRS of your pedestrian network, and always returns a directed network. It adds to the pandarm network:

- `node_type`, `stop_id`, `route_id`, `direction_id` and `feed` in `nodes_df`
- `edge_type`, `route_id` and `direction_id` in `edges_df`
- `metadata`, a record of the feeds, dates, time window and settings behind the network

Points given to `get_node_ids` and `set_pois` snap only to pedestrian nodes, while query results cover every node, so filter them on `node_type`.

`pandarm`'s `from_hdf5` and `to_crs` do not yet keep these additions or the restricted snapping. Project the pedestrian network before integrating, not after, and save `metadata` separately if you save the network.

## License

`netweave` is released under the BSD 3-Clause license. It depends on `pandarm`, which is licensed under AGPL-3.0.
