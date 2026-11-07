"""Tests for package configuration."""

import subprocess
import sys


def test_importing_netweave_creates_no_folders(tmp_path) -> None:
    code = "import netweave; netweave.settings; netweave.config"
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, check=True, capture_output=True)
    assert list(tmp_path.iterdir()) == []
