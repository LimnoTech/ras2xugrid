"""The reader on real HEC-RAS plan files, from the folder in ``HECRAS_TEST_DATA``.

The real-plan tests are marked ``local_data`` and skipped unless the folder is set. Every plan
in the folder is tested, and test ids use a plan's position (``plan0``), never its file name.
Plan files never enter the repository.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras2xugrid import list_flow_areas, open_flow_area
from ras2xugrid._hdf import RESULTS, decode
from ras2xugrid.testing import write_synthetic_plan

local_data = pytest.mark.local_data

# The one named file, with its cell count (check 1 of docs/hecras-plan-files.md).
SUMWERE = ("clearWaterTestCases.p48.hdf", 367)


def plans(folder: Path) -> list[Path]:
    """Every ``*.hdf`` in ``folder`` that holds results: a plan, not a geometry file."""
    found = []
    for path in sorted(folder.glob("*.hdf")):
        if not h5py.is_hdf5(path):
            continue
        with h5py.File(path) as file:
            if RESULTS in file:
                found.append(path)
    return found


@cache
def _plans(folder: Path) -> list[Path]:
    """``plans(folder)``, computed once per folder for collection and the tests."""
    return plans(folder)


def _folder() -> Path | None:
    value = os.environ.get("HECRAS_TEST_DATA")
    return Path(value) if value else None


def _plan_areas() -> list[tuple[int, int | None]]:
    """Each (plan position, area position) pair; a plan with no 2D area gets ``None``."""
    folder = _folder()
    if folder is None:
        return []
    pairs: list[tuple[int, int | None]] = []
    for position, path in enumerate(_plans(folder)):
        count = len(list_flow_areas(path))
        if count:
            pairs.extend((position, a) for a in range(count))
        else:
            pairs.append((position, None))
    return pairs


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "plan_area" in metafunc.fixturenames:
        pairs = _plan_areas()
        ids = [f"plan{p}-area{a}" if a is not None else f"plan{p}-noarea" for p, a in pairs]
        metafunc.parametrize("plan_area", pairs, ids=ids)
    if "plan_position" in metafunc.fixturenames:
        folder = _folder()
        count = len(_plans(folder)) if folder else 0
        metafunc.parametrize("plan_position", range(count), ids=[f"plan{i}" for i in range(count)])


def _area(folder: Path, plan_area: tuple[int, int | None]):
    position, area = plan_area
    path = _plans(folder)[position]
    if area is None:
        pytest.skip(f"{path.name} has no 2D flow area")
    return path, area


@local_data
def test_the_named_file_has_its_cell_count(hecras_test_data):
    name, cells = SUMWERE
    path = hecras_test_data / name
    if not path.exists():
        pytest.skip(f"{name} is not in HECRAS_TEST_DATA")
    assert list_flow_areas(path).iloc[0]["Cell Count"] == cells


@local_data
def test_counts_match_list_flow_areas(hecras_test_data, plan_area):
    path, position = _area(hecras_test_data, plan_area)
    areas = list_flow_areas(path)
    row = areas.iloc[position]
    uds = open_flow_area(path, area=str(areas.index[position]))
    assert uds.grid.n_face == row["Cell Count"]
    assert uds.grid.n_edge == row["faces"]
    assert uds.grid.n_node == row["face_points"]


@local_data
def test_every_result_array_is_in_the_dataset(hecras_test_data, plan_area):
    path, position = _area(hecras_test_data, plan_area)
    area = str(list_flow_areas(path).index[position])
    uds = open_flow_area(path, area=area)
    with h5py.File(path) as file:
        group_path = f"{RESULTS}/2D Flow Areas/{area}"
        if group_path not in file:
            pytest.skip(f"{path.name} has no results group for its flow area")
        group = file[group_path]
        arrays = [k for k, v in group.items() if isinstance(v, h5py.Dataset)]
        for key in arrays:
            assert key in uds.obj, f"{key} (Location {decode(group[key].attrs.get('Location'))})"
            assert uds[key].dims[0] == "time"


@local_data
def test_face_flow_runs_from_first_to_second_cell(hecras_test_data, plan_area):
    """Face Flow is positive from the first to the second cell of Faces Cell Indexes."""
    path, position = _area(hecras_test_data, plan_area)
    areas = list_flow_areas(path)
    uds = open_flow_area(path, area=str(areas.index[position]))
    if "Face Flow" not in uds or "Water Surface" not in uds:
        pytest.skip(f"{path.name} has no Face Flow and Water Surface")
    pairs = uds["Faces Cell Indexes"].values
    interior = (pairs >= 0).all(axis=1)
    surface = uds["Water Surface"].values
    flow = uds["Face Flow"].values
    head = surface[:, pairs[interior, 0]] - surface[:, pairs[interior, 1]]
    moving = flow[:, interior]
    decided = (np.abs(head) > 0.05) & (moving != 0)
    agree = np.sign(moving[decided]) == np.sign(head[decided])
    if decided.sum() <= 100:
        pytest.skip(f"{path.name}: only {decided.sum()} faces decided, too few to test")
    # 0.99 is deliberate slack; plans measured while writing this agreed 100%
    # (docs/hecras-plan-files.md).
    # No wet filter: a face between dry cells carries no flow, so `moving != 0` drops it.
    assert agree.mean() >= 0.99


# plans() itself: unmarked, so the default run covers it.


def test_plans_finds_a_plan_and_ignores_other_hdf(tmp_path):
    plan = write_synthetic_plan(tmp_path / "a.p01.hdf")
    with h5py.File(tmp_path / "geometry.g01.hdf", "w") as file:
        file.create_group("Geometry")
    assert plans(tmp_path) == [plan]


def test_plans_of_an_empty_folder_is_empty(tmp_path):
    assert plans(tmp_path) == []


def test_plans_passes_over_a_file_that_is_not_hdf5(tmp_path):
    (tmp_path / "x.hdf").write_text("not hdf5")
    assert plans(tmp_path) == []
