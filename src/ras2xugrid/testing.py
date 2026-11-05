"""A small synthetic HEC-RAS plan file, written with HEC-RAS's own paths and names.

The mesh has four real cells (three quadrilaterals and a pentagon), 14 faces in an order that is
deliberately not xugrid's derived order, and 11 ghost cells, one outside each boundary face.
Face 1 lists its cells as ``(2, 1)`` so that a face's flow sign is exercised.
"""

from __future__ import annotations

import os
from pathlib import Path

import h5py
import numpy as np
import pyproj

from ._hdf import GEOMETRY, RESULTS

CELL_COUNT = 4
N_FACES = 14
N_FACE_POINTS = 11

FACE_POINT_COORDS = np.array(
    [
        (0, 0), (1, 0), (2, 0), (3, 0), (0, 1), (1, 1),
        (2, 1), (3, 1), (2, 2), (1.5, 2.5), (1, 2),
    ],
    dtype="float64",
)  # fmt: skip

_REAL_CELLS = [[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [5, 6, 8, 9, 10]]

FACE_POINTS = np.array(
    [
        (1, 5), (2, 6), (5, 6), (0, 1), (1, 2), (2, 3), (3, 7),
        (7, 6), (6, 8), (8, 9), (9, 10), (10, 5), (5, 4), (4, 0),
    ],
    dtype="int32",
)  # fmt: skip

# Cells on each side of a face; the boundary faces f3 to f13 have ghost cells 4 to 14.
FACE_CELLS = np.array(
    [
        (0, 1), (2, 1), (1, 3), (0, 4), (1, 5), (2, 6), (2, 7),
        (2, 8), (3, 9), (3, 10), (3, 11), (3, 12), (0, 13), (0, 14),
    ],
    dtype="int32",
)  # fmt: skip

N_CELLS = 15  # real cells then ghosts
_N_TIMES = 3
_MAX_POINTS = 8


def _cells_facepoint_indexes() -> np.ndarray:
    table = np.full((N_CELLS, _MAX_POINTS), -1, dtype="int32")
    for i, cell in enumerate(_REAL_CELLS):
        table[i, : len(cell)] = cell
    for k in range(3, N_FACES):
        table[k + 1, :2] = FACE_POINTS[k]
    return table


def _centres() -> np.ndarray:
    centres = np.zeros((N_CELLS, 2))
    for i, cell in enumerate(_REAL_CELLS):
        x, y = FACE_POINT_COORDS[cell, 0], FACE_POINT_COORDS[cell, 1]
        x1, y1 = np.roll(x, -1), np.roll(y, -1)
        cross = x * y1 - x1 * y
        area = cross.sum() / 2
        centres[i] = ((x + x1) * cross).sum() / (6 * area), ((y + y1) * cross).sum() / (6 * area)
    for k in range(3, N_FACES):
        centres[k + 1] = FACE_POINT_COORDS[FACE_POINTS[k]].mean(axis=0)
    return centres


def _put(group: h5py.Group, name: str, data: np.ndarray, units: bytes, location: bytes | None):
    dataset = group.create_dataset(name, data=data)
    dataset.attrs["Units"] = np.bytes_(units)
    if location is not None:
        dataset.attrs["Location"] = np.bytes_(location)


def _write_results(file: h5py.File, area: str) -> None:
    series = file.create_group(RESULTS)
    time = series.create_dataset("Time", data=np.array([0.0, 0.5, 1.0]))
    time.attrs["Time"] = np.bytes_(b"days")
    series.create_dataset(
        "Time Date Stamp",
        data=np.array(
            [b"01JAN2020 00:00:00", b"01JAN2020 12:00:00", b"02JAN2020 00:00:00"], dtype="S18"
        ),
    )
    group = series.create_group(f"2D Flow Areas/{area}")
    t = np.arange(_N_TIMES)[:, None]
    cells = np.arange(N_CELLS)[None, :]
    faces = np.arange(N_FACES)[None, :]
    flow = ((t + 1) * (faces + 1)).astype("float32")
    _put(group, "Water Surface", (10 + 0.1 * t + cells).astype("float32"), b"ft", b"Cells")
    precipitation = np.repeat(np.array([0.0, 0.5, 1.0], dtype="float32")[:, None], N_CELLS, axis=1)
    _put(group, "Cell Cumulative Precipitation Depth", precipitation, b"in", b"Cell")
    _put(group, "Face Flow", flow, b"cfs", b"Faces")
    _put(group, "Face Cumulative Volume", np.cumsum(flow * 43200, axis=0), b"ft^3", b"Faces")
    _put(group, "Courant Number Max", np.zeros((_N_TIMES, N_CELLS), dtype="float32"), b"-", None)
    group.create_group("Boundary Conditions")


def write_synthetic_plan(
    path: str | os.PathLike[str],
    *,
    area: str = "meshArea",
    projection: bool = True,
    pipe_nodes: bool = True,
    results: bool = True,
) -> Path:
    """Write the synthetic plan to ``path`` and return it as a ``Path``."""
    path = Path(path)
    with h5py.File(path, "w") as file:
        file.attrs["File Type"] = np.bytes_(b"HEC-RAS Results")
        file.attrs["File Version"] = np.bytes_(b"HEC-RAS 6.7 synthetic")
        file.attrs["Units System"] = np.bytes_(b"US Customary")
        if projection:
            wkt = pyproj.CRS.from_epsg(2263).to_wkt("WKT1_ESRI")
            file.attrs["Projection"] = np.bytes_(wkt.encode())
        file.create_group("Plan Data/Plan Information").attrs["Plan Title"] = np.bytes_(
            b"synthetic"
        )

        attributes = np.zeros(1, dtype=[("Name", "S16"), ("Cell Count", "<i4")])
        attributes["Name"] = area.encode()
        attributes["Cell Count"] = CELL_COUNT
        file.create_dataset(f"{GEOMETRY}/Attributes", data=attributes)
        geometry = file.create_group(f"{GEOMETRY}/{area}")
        geometry.create_dataset("FacePoints Coordinate", data=FACE_POINT_COORDS)
        geometry.create_dataset("Cells FacePoint Indexes", data=_cells_facepoint_indexes())
        geometry.create_dataset("Faces FacePoint Indexes", data=FACE_POINTS)
        geometry.create_dataset("Faces Cell Indexes", data=FACE_CELLS)
        surface = np.zeros(N_CELLS)
        surface[:CELL_COUNT] = [1, 1, 1, 1.25]
        geometry.create_dataset("Cells Surface Area", data=surface.astype("float32"))
        elevation = np.full(N_CELLS, np.nan)
        elevation[:CELL_COUNT] = [5, 5, 5, 6]
        geometry.create_dataset("Cells Minimum Elevation", data=elevation.astype("float32"))
        geometry.create_dataset("Cells Center Coordinate", data=_centres())

        if pipe_nodes:
            nodes = np.zeros(2, dtype=[("Name", "S7"), ("Invert Elevation", "<f4")])
            nodes["Name"] = [b"Node 1", b"Node 2"]
            nodes["Invert Elevation"] = [4.0, 4.5]
            file.create_dataset("Geometry/Pipe Nodes/Attributes", data=nodes)
            file.create_dataset("Geometry/Pipe Nodes/Points", data=[[0.5, 0.5], [2.5, 0.5]])

        if results:
            _write_results(file, area)
    return path
