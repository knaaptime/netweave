"""GTFS feed sources: registry, download, and unzip utilities."""


import os
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from tqdm import tqdm

from netweave._logging import status
from netweave.exceptions import NetweaveError


@dataclass
class FeedRegistry:
    """Registry of named GTFS feed URLs."""

    feeds: dict[str, str] = field(default_factory=dict)

    def add(self, name: str, url: str) -> None:
        """Add a feed to the registry.

        Parameters
        ----------
        name : str
            Unique name for the feed.
        url : str
            Direct download URL for the GTFS zip file.
        """
        if not isinstance(name, str) or not isinstance(url, str):
            raise TypeError("Both name and url must be strings")
        self.feeds[name] = url

    def remove(self, name: str) -> None:
        """Remove a feed from the registry."""
        self.feeds.pop(name, None)

    def to_dict(self) -> dict[str, str]:
        """Return the registry as a dictionary."""
        return self.feeds.copy()

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "FeedRegistry":
        """Create a registry from a dictionary."""
        return cls(feeds=data.copy())


def download_feed(
    url: str,
    output_dir: str | Path,
    filename: Optional[str] = None,
    timeout: int = 300,
) -> Path:
    """Download a GTFS feed from a URL.

    Parameters
    ----------
    url : str
        Direct download URL.
    output_dir : str or pathlib.Path
        Directory to save the downloaded file.
    filename : str, optional
        Name to save the file as. If None, inferred from URL.
    timeout : int, optional
        Request timeout in seconds.

    Returns
    -------
    pathlib.Path
        Path to the downloaded file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if filename is None:
        parsed = urlparse(url)
        filename = Path(parsed.path).name or "gtfs_feed.zip"
    if not filename.endswith(".zip"):
        filename += ".zip"

    output_path = output_dir / filename

    status(f"Downloading {url} to {output_path}")
    response = requests.get(url, stream=True, timeout=timeout)
    response.raise_for_status()

    total = int(response.headers.get("content-length", 0))
    with open(output_path, "wb") as f, tqdm(
        desc=filename,
        total=total,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
    ) as pbar:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                pbar.update(len(chunk))

    status(f"Download complete: {output_path}")
    return output_path


def unzip_feed(
    zip_path: str | Path,
    output_dir: Optional[str | Path] = None,
    remove_zip: bool = False,
) -> Path:
    """Unzip a GTFS feed archive.

    Parameters
    ----------
    zip_path : str or pathlib.Path
        Path to the zip file.
    output_dir : str or pathlib.Path, optional
        Directory to extract to. If None, extracts next to the zip.
    remove_zip : bool, optional
        If True, delete the zip file after extraction.

    Returns
    -------
    pathlib.Path
        Path to the extracted directory.
    """
    zip_path = Path(zip_path)
    if output_dir is None:
        output_dir = zip_path.parent / zip_path.stem
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    status(f"Extracting {zip_path} to {output_dir}")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(output_dir)

    if remove_zip:
        zip_path.unlink()
        status(f"Removed {zip_path}")

    return output_dir
