# pandarm.Network is the only network netweave takes or returns

netweave is a data pipeline and format bridge, and all network analysis belongs to pandarm. `integrate` therefore takes a `pandarm.Network` as its pedestrian input and returns a `pandarm.Network`. There is no `IntegratedNetwork`, because it only ever piped into a conversion. netweave has no OSM loader, because pandarm has one, and no wrappers around pandarm's queries. `TransitNetwork` stays as plain tables, because it is built without a pedestrian network, is worth inspecting by itself, and can be joined to several pedestrian networks without building contraction hierarchies nobody queries.

## Consequences

pandarm's constructor keeps only coordinates, impedances and geometry, so netweave adds its node and edge labels and `metadata` to the finished object and restricts snapping by replacing `kdtree`. This targets pandarm 0.0.5, and these gaps should be closed in pandarm:

- `from_hdf5` and `to_crs` rebuild the network through the constructor, which drops the added columns, `metadata` and the restricted snapping. `save_hdf5` does write the added columns to the file.
- `from_hdf5` tests `"crs" in store.keys()`, but HDFStore keys begin with `/`, so a projected network reloads as EPSG:4326.
- `to_crs` leaves `Network.crs` at 4326 and sets the real CRS only on `nodes_df` and `edges_df`, so `integrate` reads it from `nodes_df`. It also keeps only the first impedance, and fails on a network without edge geometry.
- There is no supported way to limit which nodes points snap to.
- `initializeCategory` asserts `node_id << av.size()`, apparently meaning `<`. The assertion fails for node position 0, so a point of interest nearest the first node aborts the process.
- Costs become fixed-point integers, so `inf`, `NaN` and `1e9` silently act as nearly free. `integrate` refuses them, but other callers are not protected.

Until then, project the pedestrian network before integrating rather than calling `to_crs` afterwards, and keep `metadata` separately if a network will be saved.
