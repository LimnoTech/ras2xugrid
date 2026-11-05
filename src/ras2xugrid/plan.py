"""Reading what a HEC-RAS plan file holds: its 2D flow areas and its pipe nodes."""

from __future__ import annotations

import os
import warnings
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
import pyproj
import xarray as xr
import xugrid as xu

from ._hdf import GEOMETRY, RESULTS, decode, open_hdf, parse_time_date_stamp

_PIPE_NODES = "Geometry/Pipe Nodes"
_PLAN_INFORMATION = "Plan Data/Plan Information"


def _attribute_frame(table: Any) -> pd.DataFrame:
    """A compound ``Attributes`` dataset as a frame, byte-string fields decoded."""
    rows = table[()]
    data: dict[str, Any] = {}
    for field in rows.dtype.names or ():
        column = rows[field]
        if column.dtype.kind == "S":
            data[field] = [decode(value) for value in column]
        else:
            data[field] = column
    return pd.DataFrame(data)


def _require(parent: Any, key: str, area: str | None, where: str) -> Any:
    """``parent[key]``, or a ``ValueError`` naming the area and the HDF path that is missing."""
    if key not in parent:
        of_area = f"flow area {area!r}" if area is not None else "the file"
        raise ValueError(f"{of_area} has no {where}/{key}")
    return parent[key]


def _text_attr(attrs: Any, key: str) -> Any:
    return decode(attrs[key]) if key in attrs else pd.NA


def list_flow_areas(path: str | os.PathLike[str] | Any) -> pd.DataFrame:
    """List the 2D flow areas of a plan file, one row per area, indexed by ``name``.

    Areas come from the ``Geometry/2D Flow Areas/Attributes`` table, never from listing the group,
    which also holds datasets that are not areas. Columns: HEC-RAS's ``Cell Count``, ``faces`` and
    ``face_points`` (row counts of ``Faces FacePoint Indexes`` and ``FacePoints Coordinate``),
    the root ``File Version`` and the ``Plan Title`` (NA when absent).
    """
    with open_hdf(path) as file:
        file_version = _text_attr(file.attrs, "File Version")
        info = file.get(_PLAN_INFORMATION)
        plan_title = _text_attr(info.attrs, "Plan Title") if info is not None else pd.NA
        table = file.get(f"{GEOMETRY}/Attributes")
        names: list[str] = []
        counts: list[Any] = []
        faces: list[int] = []
        face_points: list[int] = []
        if table is not None:
            attributes = _attribute_frame(table)
            for name, count in zip(attributes["Name"], attributes["Cell Count"], strict=True):
                group = _require(file[GEOMETRY], name, name, GEOMETRY)
                names.append(name)
                counts.append(count)
                faces.append(
                    _require(group, "Faces FacePoint Indexes", name, f"{GEOMETRY}/{name}").shape[0]
                )
                face_points.append(
                    _require(group, "FacePoints Coordinate", name, f"{GEOMETRY}/{name}").shape[0]
                )
    frame = pd.DataFrame(
        {
            "Cell Count": np.asarray(counts, dtype="int64"),
            "faces": np.asarray(faces, dtype="int64"),
            "face_points": np.asarray(face_points, dtype="int64"),
            "File Version": np.array([file_version] * len(names), dtype="object"),
            "Plan Title": np.array([plan_title] * len(names), dtype="object"),
        },
        index=pd.Index(names, name="name", dtype="object"),
    )
    return frame


def pipe_nodes(path: str | os.PathLike[str] | Any) -> pd.DataFrame:
    """Read the pipe nodes of a plan file: ``Name``, ``x``, ``y``, then every other field verbatim.

    Returns an empty frame with columns ``Name``, ``x``, ``y`` when the file has no pipe network.
    """
    with open_hdf(path) as file:
        group = file.get(_PIPE_NODES)
        if group is None or "Attributes" not in group:
            return pd.DataFrame({"Name": pd.Series([], dtype="object"), "x": [], "y": []}).astype(
                {"x": "float64", "y": "float64"}
            )
        attributes = _attribute_frame(group["Attributes"])
        points = np.asarray(_require(group, "Points", None, _PIPE_NODES)[()], dtype="float64")
    frame = attributes.copy()
    frame.insert(1, "x", points[:, 0])
    frame.insert(2, "y", points[:, 1])
    return frame


_CELL_LOCATIONS = {"Cell", "Cells"}  # a HEC-RAS 6.7 plan writes the singular on cumulative depths
_FACE_LOCATIONS = {"Face", "Faces"}
_STATIC_CELLS = ("Cells Surface Area", "Cells Minimum Elevation")
_DEPTH_DERIVATION = "Water Surface - Cells Minimum Elevation (ras2xugrid; not a HEC-RAS output)"
_GHOST_COMMENT = "indexes of ghost cells (>= Cell Count) written as -1"


def _verbatim(attrs: Any) -> dict[str, Any]:
    """HEC-RAS attributes as written, byte strings decoded to ``str``."""
    return {
        key: decode(value) if isinstance(value, bytes | np.bytes_) else value
        for key, value in attrs.items()
    }


def _choose_area(names: list[str], area: str | None) -> str:
    if area is None:
        if len(names) != 1:
            raise ValueError(
                f"the file holds {len(names)} 2D flow areas, so name one with area=: {names}"
            )
        return names[0]
    if area not in names:
        raise KeyError(f"no 2D flow area {area!r}; the file holds {names}")
    return area


def _grid_crs(file_attrs: Any, crs: Any) -> pyproj.CRS | None:
    if crs is not None:
        return pyproj.CRS.from_user_input(crs)
    if "Projection" not in file_attrs:
        warnings.warn(
            "the plan file has no Projection attribute and no crs= was given: the CRS is unset",
            UserWarning,
            stacklevel=3,
        )
        return None
    return pyproj.CRS.from_wkt(decode(file_attrs["Projection"]))


def _time_selection(file: Any, time: slice | None) -> tuple[pd.DatetimeIndex, slice] | None:
    if f"{RESULTS}/Time Date Stamp" not in file:
        return None
    times = parse_time_date_stamp(file[f"{RESULTS}/Time Date Stamp"][()])
    if time is None:
        return times, slice(None)
    positions = times.slice_indexer(time.start, time.stop, time.step)
    if len(range(*positions.indices(len(times)))) == 0:
        raise ValueError(
            f"time={time!r} selects no steps: the file runs from {times[0]} to {times[-1]}"
        )
    return times, positions


def _check_lengths(file: Any, name: str, times: pd.DatetimeIndex, results: Any) -> None:
    """Raise when ``Time Date Stamp``, ``Time`` and the results' time axis disagree in length.

    Only the arrays ``open_flow_area`` reads count (``Location`` of Cell, Cells, Face or Faces):
    other 2-D arrays in the group need not be time-first.
    """
    lengths = {f"Time Date Stamp: {len(times)}": len(times)}
    if "Time" in file[RESULTS]:
        lengths[f"Time: {file[f'{RESULTS}/Time'].shape[0]}"] = file[f"{RESULTS}/Time"].shape[0]
    for key, dataset in results.items():
        if not hasattr(dataset, "shape") or len(dataset.shape) != 2:
            continue
        location = decode(dataset.attrs["Location"]) if "Location" in dataset.attrs else ""
        if location in _CELL_LOCATIONS | _FACE_LOCATIONS:
            lengths[f"{key}: {dataset.shape[0]}"] = dataset.shape[0]
    if len(set(lengths.values())) > 1:
        raise ValueError(
            f"time axes of flow area {name!r} disagree in length ({', '.join(lengths)})"
        )


def open_flow_area(
    path: str | os.PathLike[str] | Any,
    area: str | None = None,
    *,
    variables: Sequence[str] | None = None,
    time: slice | None = None,
    crs: Any = None,
) -> xu.UgridDataset:
    """Open one HEC-RAS 2D flow area as an ``xugrid.UgridDataset``, real cells only.

    HEC-RAS cells are the mesh faces (ghost cells dropped) and HEC-RAS faces are the mesh edges,
    in HEC-RAS's own order. Results keep their HEC-RAS names and attributes verbatim, with the
    CF ``units`` set to HEC-RAS's ``Units``. ``Faces Cell Indexes`` is a data variable (ghost
    neighbours written as -1) whose column order fixes the sign of a face's result.

    Results are on ``time`` (timestamps from ``Time Date Stamp``) with ``time_days`` beside it:
    HEC-RAS's ``Time``, in days, its name kept in ``attrs["hecras_name"]`` and its ``Time`` =
    ``days`` attribute as written. It is not called ``Time`` because ``time`` and ``Time`` are
    the same zarr path on a case-insensitive filesystem, so ``to_zarr`` would fail.

    ``variables`` selects results by HEC-RAS name (the static ``Cells Surface Area`` and
    ``Cells Minimum Elevation`` are always kept), ``time`` is a slice of timestamps, and ``crs``
    overrides the file's ``Projection``. A file without ``Cell Hydraulic Depth`` gets a derived
    ``depth`` variable, labelled as such.
    """
    with open_hdf(path) as file:
        table = file.get(f"{GEOMETRY}/Attributes")
        if table is None:  # a 1D-only plan
            _choose_area([], area)
        attributes = _attribute_frame(table)
        names = list(attributes["Name"])
        name = _choose_area(names, area)
        n_real = int(attributes["Cell Count"].to_numpy()[names.index(name)])
        geometry = _require(file[GEOMETRY], name, name, GEOMETRY)
        grid_crs = _grid_crs(file.attrs, crs)

        where = f"{GEOMETRY}/{name}"
        coords = np.asarray(_require(geometry, "FacePoints Coordinate", name, where)[()], "float64")
        cell_nodes = np.asarray(
            _require(geometry, "Cells FacePoint Indexes", name, where)[:n_real], dtype="int64"
        )
        edge_nodes = np.asarray(
            _require(geometry, "Faces FacePoint Indexes", name, where)[()], dtype="int64"
        )
        face_cells = np.asarray(
            _require(geometry, "Faces Cell Indexes", name, where)[()], dtype="int64"
        )
        face_cells[face_cells >= n_real] = -1
        grid = xu.Ugrid2d(
            coords[:, 0],
            coords[:, 1],
            -1,
            cell_nodes,
            name="mesh2d",
            edge_node_connectivity=edge_nodes.copy(),
            start_index=0,
            crs=grid_crs,
        )
        # xugrid's Ugrid2d has no edge_face_connectivity argument: it derives the pairs, in its
        # own column order, on first access. HEC-RAS's order fixes the sign of a face's result, so
        # the cached value is set to HEC-RAS's pairs (xugrid 0.15.3, ugrid/ugrid2d.py). Sections
        # read orientation from the "Faces Cell Indexes" variable, and a test pins this.
        grid._edge_face_connectivity = face_cells.astype("int32")
        faces, edges = grid.face_dimension, grid.edge_dimension

        data: dict[str, xr.Variable] = {}
        for static in _STATIC_CELLS:
            dataset = _require(geometry, static, name, where)
            data[static] = xr.Variable((faces,), dataset[:n_real], _verbatim(dataset.attrs))
        data["Faces Cell Indexes"] = xr.Variable(
            (edges, "two"), face_cells.astype("int32"), {"comment": _GHOST_COMMENT}
        )

        coordinates: dict[str, xr.Variable] = {}
        selection = _time_selection(file, time)
        results = file.get(f"{RESULTS}/2D Flow Areas/{name}")
        if selection is None or results is None:
            missing_path = (
                f"{RESULTS}/Time Date Stamp"
                if selection is None
                else f"{RESULTS}/2D Flow Areas/{name}"
            )
            if variables is not None:
                raise KeyError(
                    f"variables={list(variables)} asked for, but the file has no {missing_path}"
                )
            if time is not None:
                raise ValueError(f"time={time!r} asked for, but the file has no {missing_path}")
        else:
            times, rows = selection
            _check_lengths(file, name, times, results)
            coordinates["time"] = xr.Variable(("time",), times[rows].to_numpy())
            if "Time" in file[RESULTS]:
                days = file[f"{RESULTS}/Time"]
                # No CF ``units`` of "days": xarray would decode a bare time unit as a timedelta
                # on reopen and change the values a reader gets back.
                coordinates["time_days"] = xr.Variable(
                    ("time",), days[rows], {**_verbatim(days.attrs), "hecras_name": "Time"}
                )
            wanted = list(variables) if variables is not None else None
            available: list[str] = []
            for key, dataset in results.items():
                if not hasattr(dataset, "shape"):
                    continue  # sub-groups (Boundary Conditions, ...) are not results
                location = decode(dataset.attrs["Location"]) if "Location" in dataset.attrs else ""
                if location in _CELL_LOCATIONS:
                    dim, width = faces, n_real
                elif location in _FACE_LOCATIONS:
                    dim, width = edges, len(edge_nodes)
                else:
                    warnings.warn(
                        f"skipped {key!r}: its Location is {location or 'missing'!r}, not "
                        "Cells or Faces",
                        UserWarning,
                        stacklevel=2,
                    )
                    continue
                available.append(key)
                if wanted is None or key in wanted:
                    values = dataset[rows, :width]
                    attrs = _verbatim(dataset.attrs)
                    if "Units" in attrs:
                        attrs["units"] = attrs["Units"]
                    data[key] = xr.Variable(("time", dim), values, attrs)
            missing = [v for v in wanted or [] if v not in available]
            if missing:
                raise KeyError(f"unknown variables {missing}; available: {available}")
            if (
                "Water Surface" in data
                and "Cell Hydraulic Depth" not in results
                and "Water Surface" in available
            ):
                surface = data["Water Surface"]
                depth = surface.values - data["Cells Minimum Elevation"].values
                data["depth"] = xr.Variable(
                    surface.dims,
                    depth,
                    {"units": surface.attrs.get("units", ""), "derivation": _DEPTH_DERIVATION},
                )

        flow_attrs: dict[str, Any] = {"flow_area": name}
        for key in ("File Version", "Units System"):
            if key in file.attrs:
                flow_attrs[key] = decode(file.attrs[key])
        info = file.get(_PLAN_INFORMATION)
        if info is not None and "Plan Title" in info.attrs:
            flow_attrs["Plan Title"] = decode(info.attrs["Plan Title"])

    ds = xr.Dataset(data, coords=coordinates, attrs=flow_attrs)
    # xugrid's annotation says a class; its code takes grid instances (xugrid 0.15.3)
    return xu.UgridDataset(ds, grids=[grid])  # pyrefly: ignore[bad-argument-type]
