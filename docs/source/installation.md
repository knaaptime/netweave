# Installation

netweave supports Python >= 3.10. We recommend using [miniforge] or [pixi].

## Installing from source

netweave has not been released, so install it from the repository. The
environment file brings in `pandarm`, which netweave requires, built by
conda-forge:

```bash
git clone https://github.com/knaaptime/netweave.git
cd netweave
conda env create -f environment.yml
conda activate netweave
pip install -e . --no-deps
```

The `plus` extra adds `osmnx`, which `pandarm.Network.from_gdf` uses to download
pedestrian networks from OpenStreetMap, and `pyarrow`, which reads GTFS files
faster. The environment file already includes both.

## Transitland

`netweave.search_feeds` and `netweave.fetch_feeds` query the
[Transitland](https://www.transit.land) API, which needs a free API key. Pass it
as `api_key`, or set it once in the environment:

```bash
export TRANSITLAND_API_KEY="your-key"
```

Feeds you already have need no key: read them with `netweave.load_feed`.

## Building the docs

```bash
cd docs
make html
```

Every build runs the user guide from start to finish, as a test of the whole pipeline, so it needs `TRANSITLAND_API_KEY` and network access. Clear the notebook's outputs before committing it, with `make clearnbs`.

## Verifying the installation

```python
import netweave
print(netweave.__version__)
```

[miniforge]: https://github.com/conda-forge/miniforge
[pixi]: https://pixi.sh
