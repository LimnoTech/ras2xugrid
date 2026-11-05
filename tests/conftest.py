"""Shared fixtures: the synthetic plan, and the folder of real plan files when one is set."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ras2xugrid.testing import write_synthetic_plan


@pytest.fixture
def synthetic_plan(tmp_path: Path) -> Path:
    return write_synthetic_plan(tmp_path / "synthetic.p01.hdf")


@pytest.fixture
def hecras_test_data() -> Path:
    folder = os.environ.get("HECRAS_TEST_DATA")
    if not folder:
        pytest.skip("HECRAS_TEST_DATA is not set")
    return Path(folder)
