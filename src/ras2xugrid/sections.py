"""Cross sections: sets of HEC-RAS faces with a sign, and results summed over them."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
import pyproj
import shapely
import xarray as xr
import xugrid as xu

_INDEX_NAMES = ["cross_section", "edge"]
_FACE_CELLS = "Faces Cell Indexes"


def _face_cells(uds: Any) -> np.ndarray:
    """The file's own ``Faces Cell Indexes`` (HEC-RAS's column order, ghosts as -1).

    Raises ``ValueError`` when the variable is missing or no longer matches the grid's own
    face pairs: it is a data variable, so a subset (``ugrid.sel``, ``clip_box``) renumbers the
    grid but leaves it with the old numbers.
    """
    if _FACE_CELLS not in uds.obj:
        raise ValueError(
            f"the dataset has no {_FACE_CELLS!r}, which sections need to orient each face; "
            "build sections on the dataset open_flow_area returned"
        )
    face_cells = np.asarray(uds[_FACE_CELLS].values, dtype="int64")
    grid_cells = np.asarray(uds.ugrid.grid.edge_face_connectivity, dtype="int64")
    if face_cells.shape != grid_cells.shape or not np.array_equal(
        np.sort(face_cells, axis=1), np.sort(grid_cells, axis=1)
    ):
        raise ValueError(
            f"{_FACE_CELLS!r} no longer matches its grid; was the dataset subset? "
            "build sections on the dataset open_flow_area returned"
        )
    return face_cells


def _frame(rows: list[tuple[str, int, int]]) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples([(s, e) for s, e, _ in rows], names=_INDEX_NAMES)
    return pd.DataFrame({"sign": np.array([r[2] for r in rows], dtype="int8")}, index=index)


def boundary_faces(uds: Any, cells: Mapping[str, Sequence[int]]) -> pd.DataFrame:
    """The faces on the boundary of each named set of cells, with the sign of outflow.

    A face belongs to a section when exactly one of its two cells is in the set; a ghost cell
    (-1 in ``Faces Cell Indexes``) is outside. ``sign`` is +1 when the face's first cell is in
    the set, so positive is flow out of the set. Returns a frame indexed by
    (``cross_section``, ``edge``), sections in the order given and edges ascending, with one
    ``int8`` column ``sign``. An empty set, or a cell index outside ``0 ... n_face - 1`` (a
    ghost, a negative number, a point that fell outside the mesh), raises ``ValueError`` naming
    the section.
    """
    face_cells = _face_cells(uds)
    n_cells = int(uds.grid.n_face)
    rows: list[tuple[str, int, int]] = []
    for name, members in cells.items():
        indexes = np.asarray(list(members), dtype="int64")
        if indexes.size == 0:
            raise ValueError(f"cross section {name!r} has no cells")
        bad = indexes[(indexes < 0) | (indexes >= n_cells)]
        if bad.size:
            raise ValueError(
                f"cross section {name!r} lists cell indexes that are not real cells "
                f"(0 ... {n_cells - 1}): {sorted(set(bad.tolist()))}"
            )
        inside = np.zeros(n_cells + 1, dtype=bool)  # the last slot takes the ghost index -1
        inside[indexes] = True
        first = inside[face_cells[:, 0]]
        second = inside[face_cells[:, 1]]
        for edge in np.flatnonzero(first != second):
            rows.append((name, int(edge), 1 if first[edge] else -1))
    return _frame(rows)


def faces_from_table(uds: Any, df: pd.DataFrame) -> pd.DataFrame:
    """Cross-section faces from a table of ``CrossSection``, ``Face`` and ``US_Cell`` columns.

    Each row's ``sign`` is +1 when ``US_Cell`` is the face's first cell in the file's
    ``Faces Cell Indexes`` and -1 when it is the second; any other ``US_Cell`` raises
    ``ValueError`` naming the row. Rows for one (section, face) are summed and faces whose signs
    cancel are dropped, so a face shared by two cells of a section (listed once from each side)
    leaves, as in :func:`boundary_faces`, and the frame has the same form.
    """
    face_cells = _face_cells(uds)
    n_faces = len(face_cells)
    n_cells = int(uds.grid.n_face)
    sections = df["CrossSection"].astype(str).tolist()
    sums: dict[str, dict[int, int]] = {}
    for row, (section, face, us_cell) in enumerate(
        zip(sections, df["Face"].tolist(), df["US_Cell"].tolist(), strict=True)
    ):
        if pd.isna(face) or pd.isna(us_cell):
            raise ValueError(
                f"row {row} (CrossSection {section!r}): Face {face} or US_Cell {us_cell} is missing"
            )
        if face != int(face) or us_cell != int(us_cell):
            raise ValueError(
                f"row {row} (CrossSection {section!r}): Face {face} and US_Cell {us_cell} "
                "must be whole numbers"
            )
        face, us_cell = int(face), int(us_cell)
        if not 0 <= face < n_faces:
            raise ValueError(
                f"row {row} (CrossSection {section!r}): Face {face} is not a face (0 ... "
                f"{n_faces - 1})"
            )
        if not 0 <= us_cell < n_cells:
            raise ValueError(
                f"row {row} (CrossSection {section!r}, Face {face}): US_Cell {us_cell} is not a "
                f"real cell (0 ... {n_cells - 1})"
            )
        first, second = face_cells[face]
        if us_cell == first:
            sign = 1
        elif us_cell == second:
            sign = -1
        else:
            raise ValueError(
                f"row {row} (CrossSection {section!r}, Face {face}): US_Cell {us_cell} is "
                f"neither of the face's cells ({first}, {second})"
            )
        per_face = sums.setdefault(section, {})
        per_face[face] = per_face.get(face, 0) + sign
        if abs(per_face[face]) > 1:
            raise ValueError(
                f"cross section {section!r}: Face {face} is listed twice with the same sign "
                f"(row {row}); a face is listed once per side"
            )
    rows: list[tuple[str, int, int]] = []
    for section, per_face in sums.items():
        kept = [(section, face, total) for face, total in sorted(per_face.items()) if total]
        if not kept:
            raise ValueError(f"cross section {section!r}: every face cancels, so it has none")
        rows.extend(kept)
    return _frame(rows)


def _check_chain(name: str, node_pairs: np.ndarray) -> None:
    """Raise ``ValueError`` naming the section unless the faces form one open path.

    ``node_pairs`` holds each selected face's two face points, shape ``(n, 2)``. The faces form
    a path when they are connected, no face point is on more than two of them and exactly two
    face points are on only one: a branch (a face point on three or more), a gap (more than one
    connected piece) and a closed loop (no ends) each raise with their own message.
    """
    points, inverse = np.unique(node_pairs, return_inverse=True)
    pairs = inverse.reshape(node_pairs.shape)
    degree = np.bincount(pairs.ravel(), minlength=len(points))
    if (degree > 2).any():
        where = points[np.flatnonzero(degree > 2)[0]]
        raise ValueError(
            f"cross section {name!r}: the faces branch at face point {where}; "
            "a line's faces must form one chain"
        )
    parent = list(range(len(points)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in pairs:
        parent[find(int(a))] = find(int(b))
    if len({find(i) for i in range(len(points))}) > 1:
        raise ValueError(
            f"cross section {name!r}: the faces have a gap, they do not form one chain "
            "(does the line leave the mesh and come back, or cross a perimeter face?)"
        )
    if not (degree == 1).any():
        raise ValueError(
            f"cross section {name!r}: the faces form a closed loop; for the boundary of an "
            "area use boundary_faces"
        )


def _named_lines(uds: Any, lines: Any) -> list[tuple[str, shapely.LineString]]:
    if not isinstance(lines, (Mapping, pd.DataFrame, pd.Series)):
        raise TypeError(
            "lines must be a mapping of name to shapely.LineString, a (Geo)DataFrame with a "
            f"'geometry' column, or a (Geo)Series of LineStrings, not {type(lines).__name__}"
        )
    if isinstance(lines, (pd.DataFrame, pd.Series)):
        if isinstance(lines, pd.DataFrame):
            if "geometry" not in lines:
                raise ValueError("lines is a DataFrame without a 'geometry' column")
            geometries = lines["geometry"]
        else:
            geometries = lines
        crs = getattr(lines, "crs", None)
        grid_crs = uds.grid.crs
        if crs is not None and grid_crs is not None:
            if pyproj.CRS.from_user_input(crs) != pyproj.CRS.from_user_input(grid_crs):
                raise ValueError(
                    f"the lines' CRS ({pyproj.CRS.from_user_input(crs).to_string()}) differs from "
                    f"the grid's ({pyproj.CRS.from_user_input(grid_crs).to_string()})"
                )
        pairs = [
            (str(name), geometry) for name, geometry in zip(lines.index, geometries, strict=True)
        ]
    else:
        pairs = [(str(name), geometry) for name, geometry in lines.items()]
    if not pairs:
        raise ValueError("no lines were given")
    names = [name for name, _ in pairs]
    duplicated = [name for name in dict.fromkeys(names) if names.count(name) > 1]
    if duplicated:
        raise ValueError(f"cross section names must be unique; {duplicated[0]!r} is repeated")
    for name, geometry in pairs:
        if not isinstance(geometry, shapely.LineString) or isinstance(geometry, shapely.LinearRing):
            raise TypeError(
                f"cross section {name!r} must be a shapely.LineString, not "
                f"{type(geometry).__name__}"
            )
        coords = np.asarray(geometry.coords)[:, :2]
        if len(np.unique(coords, axis=0)) < 2:
            raise ValueError(f"cross section {name!r} has fewer than two distinct points")
    return pairs


def cross_section_faces(
    uds: Any,
    lines: Any,
    *,
    max_distance: float | None = None,
) -> pd.DataFrame:
    """The HEC-RAS faces each named line crosses, with the sign of flow across the line.

    ``lines`` maps a section name to a :class:`shapely.LineString`; a pandas or geopandas frame
    with a ``geometry`` column, or a Series of LineStrings, also works, its index giving the
    names (as ``str``). A frame's or Series' ``crs`` must equal the grid's when both are set.
    A face is selected, as in xugrid's ``snap_to_grid``, when the part of the line inside a
    cell puts that cell's centroid and the centroid of the neighbouring cell across the face on
    opposite sides of the line, and the line's segment crosses the straight line joining the two
    centroids (xugrid's own docstring speaks of "the centroid of the edge", but its code
    never uses the face's midpoint). So a line that grazes a corner or only touches a face is
    not enough, and the selected faces form a staircase beside the line. On the synthetic plan
    the line y = 0.5 across c0, c1 and c2 selects face 2 (c1 | c3), not faces 0 and 1. A cell
    whose centroid lies exactly on the line may be counted on either side, so the staircase may
    pass either side of that cell; the signs stay consistent.
    ``sign`` is +1 when the face's first cell (HEC-RAS's column order) is on the line's left,
    so positive flow crosses the line from left to right, standing at its start and facing its
    end; reversing a line flips every sign. For a line that crosses the mesh from edge to edge,
    so that the cells on its left are defined, this agrees with :func:`boundary_faces`: for
    those cells, its interior faces are these faces with the same signs. A face whose two
    cells are equally far to one side of the line (a tie) raises, naming the section.

    ``max_distance`` (default 0, meaning no vertex moves) is xugrid's ``max_snap_distance``: a
    line vertex within it of a face point moves onto the nearest one before faces are selected.

    A face with a ghost cell (a perimeter face) is never selected, because xugrid skips it, so a
    line ending at the mesh edge leaves out the perimeter face it meets. A line that leaves the
    mesh counts only where it is inside; one that leaves and re-enters leaves a gap and raises.
    The check that a line crosses some face uses the line as drawn, before ``max_distance`` moves
    its vertices, so a line that reaches the mesh only once snapped is refused. A line should not
    double back across a face it has already crossed: xugrid selects by centroids, so even a
    zig-zag within one cell can select a face from both sides and raise "both ways".
    The selected faces must form one chain of faces joined at face points. Returns a frame
    indexed by (``cross_section``, ``edge``), sections in the order given and edges ascending,
    with one ``int8`` column ``sign``. A non-``LineString``, a line crossing or selecting no
    face, a face crossed back with the opposite sign, a gap, a branch or a closed loop raises
    naming the section.
    """
    face_cells = _face_cells(uds)
    named = _named_lines(uds, lines)
    snap = 0.0 if max_distance is None else max_distance
    if isinstance(snap, bool) or not isinstance(snap, (int, float, np.integer, np.floating)):
        raise TypeError(f"max_distance must be a number or None, not {max_distance!r}")
    if not np.isfinite(snap) or snap < 0:
        raise ValueError(f"max_distance must be a finite number of at least 0, not {max_distance}")
    grid = uds.grid
    centroids = np.asarray(grid.centroids)
    edge_nodes = np.asarray(grid.edge_node_connectivity)
    rows: list[tuple[str, int, int]] = []
    for name, line in named:
        coords = np.asarray(line.coords, dtype="float64")[:, :2]
        segments = np.stack([coords[:-1], coords[1:]], axis=1)
        # xugrid's snap_to_grid (ugrid/snapping.py:496-552) is not used: it needs geopandas
        # (:353-365) and keeps one line per edge (:540-542). create_snap_to_grid_dataframe
        # (:367-490) returns the original edge indices and the selected segment in the line's
        # direction; it reads lines only through ``.geometry.to_numpy()`` (:247-252), so a
        # plain DataFrame serves. It raises on a line crossing no face (:467-469), checked first.
        if len(grid.celltree.intersect_edges(segments)[0]) == 0:
            raise ValueError(f"cross section {name!r} crosses no face of the mesh")
        try:
            selected = xu.create_snap_to_grid_dataframe(
                pd.DataFrame({"geometry": [line]}), grid, snap
            )
        except ValueError as error:
            # xugrid 0.15.3 crashes with this message when the snapped line crosses no face;
            # test_a_line_that_crosses_no_face_once_snapped_raises_naming_the_section is the
            # tripwire if a later xugrid words it differently or fixes the crash. The
            # ``snap == 0`` clause is a safety net only: with snap == 0 the pre-check on the
            # unsnapped line has already raised.
            if snap == 0 or "negative dimensions" not in str(error):
                raise
            raise ValueError(
                f"cross section {name!r} crosses no face once its vertices within "
                f"max_distance={snap} of a face point move onto it"
            ) from error
        if len(selected) == 0:
            raise ValueError(
                f"cross section {name!r} selects no face (it stays inside one cell, or crosses "
                "only perimeter faces)"
            )
        signs: dict[int, int] = {}
        for edge, x0, y0, x1, y1 in zip(
            selected["edge_index"], selected["x0"], selected["y0"], selected["x1"],
            selected["y1"], strict=True,
        ):  # fmt: skip
            edge = int(edge)
            first, second = (int(c) for c in face_cells[edge])
            if first < 0 or second < 0:  # xugrid skips these; a safety net
                raise ValueError(
                    f"cross section {name!r} selected face {edge}, which has a ghost cell"
                )
            # which of the face's two cells is on the left of the selected segment: the one with
            # the larger cross product (xugrid selects on a slightly tilted segment, so a centroid
            # exactly on the line is on a side there and on neither here)
            dx, dy = x1 - x0, y1 - y0
            cross_first = dx * (centroids[first, 1] - y0) - dy * (centroids[first, 0] - x0)
            cross_second = dx * (centroids[second, 1] - y0) - dy * (centroids[second, 0] - x0)
            if cross_first == cross_second:
                raise ValueError(
                    f"cross section {name!r}: both cells of face {edge} lie on the same side of, "
                    "or on, the line's segment, so it cannot be oriented"
                )
            sign = 1 if cross_first > cross_second else -1
            if signs.setdefault(edge, sign) != sign:
                raise ValueError(
                    f"cross section {name!r} crosses edge {edge} both ways, so its sign is "
                    "ambiguous"
                )
        edges = sorted(signs)
        _check_chain(name, edge_nodes[edges])
        rows.extend((name, edge, signs[edge]) for edge in edges)
    return _frame(rows)


def cross_section_series(
    uds: Any,
    faces: pd.DataFrame,
    variables: Sequence[str] = ("Face Flow", "Face Cumulative Volume"),
) -> xr.Dataset:
    """Sum face results over each cross section, as a Dataset on (``time``, ``cross_section``).

    Each variable keeps its HEC-RAS name and attributes and gains ``derivation``. Sections are in
    the order they first appear in ``faces``. A variable that is not on the faces (edges) raises
    ``ValueError``. Sums are accumulated in float64 and returned as float64.
    """
    _face_cells(uds)  # refuses a dataset whose face numbering no longer fits its grid
    edge_dim = uds.grid.edge_dimension
    if len(faces) == 0:
        raise ValueError("no faces: the cross-section table is empty")
    if faces.index.duplicated().any():
        section, edge = faces.index[faces.index.duplicated()][0]
        raise ValueError(f"cross section {section!r} lists edge {edge} more than once")
    sections = faces.index.get_level_values("cross_section").to_numpy()
    all_edges = faces.index.get_level_values("edge").to_numpy(dtype="int64")
    signs = faces["sign"].to_numpy(dtype="float64")
    names = list(dict.fromkeys(sections))
    n_edges = int(uds.grid.n_edge)
    outside = (all_edges < 0) | (all_edges >= n_edges)
    if outside.any():
        raise ValueError(
            f"cross section {sections[outside][0]!r} lists edge {all_edges[outside][0]} "
            f"outside 0 ... {n_edges - 1}"
        )
    # Each section is summed over its own faces only, so a NaN in one never reaches another.
    positions = {name: np.flatnonzero(sections == name) for name in names}
    needed, inverse = np.unique(all_edges, return_inverse=True)

    ds = uds.obj
    data: dict[str, xr.Variable] = {}
    for name in variables:
        if name not in ds:
            raise KeyError(f"no variable {name!r}; the dataset holds {list(ds.data_vars)}")
        source = ds[name]
        if source.dims != ("time", edge_dim):
            raise ValueError(
                f"{name!r} is on {source.dims}, not on the faces ('time', {edge_dim!r})"
            )
        values = source.isel({edge_dim: needed}).values.astype("float64")
        summed = np.stack(
            [values[:, inverse[idx]] @ signs[idx] for idx in positions.values()], axis=1
        )
        attrs = dict(source.attrs)
        attrs["derivation"] = f"sum over the cross section's faces of sign × {name}"
        data[name] = xr.Variable(("time", "cross_section"), summed, attrs)

    coords: dict[str, Any] = {"cross_section": np.array(names, dtype=object)}
    for key in ("time", "time_days"):
        if key in ds.coords:
            coords[key] = ds.coords[key].variable
    return xr.Dataset(data, coords=coords)
