# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.6
#   kernelspec:
#     display_name: default
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Reading a HEC-RAS 2D plan file with `ras2xugrid`: Sumwere Creek
#
# `ras2xugrid` reads a [HEC-RAS](https://www.hec.usace.army.mil/software/hec-ras/) 2D plan file
# (HDF5) into [xugrid](https://deltares.github.io/xugrid/): the mesh as a `xugrid.Ugrid2d` and
# the results as a `xugrid.UgridDataset`, with HEC-RAS's variable names, attributes and `Units`
# strings kept exactly as HEC-RAS writes them. It runs on any operating system and needs no HEC-RAS
# installation.
#
# This notebook is written first for people who read HEC-RAS files with hand-written `h5py`
# scripts. Each section says which of these chores it replaces (the
# [design note](../docs/design.md) describes what the package does and why):
#
# 1. build cell, face and face-point GeoDataFrames by hand to find the mesh pieces that matter;
# 2. pick outlet cells and filter `Faces Cell Indexes` by hand to find their faces;
# 3. keep stream sections as hand-made lists of faces (here: draw a line instead);
# 4. sum a face variable over a section, flipping signs by hand;
# 5. build the time axis from `Time` and a start date typed per plan, and set the CRS by hand.
#
# The data are ClearWater-riverine's **Sumwere Creek** test case (367 cells), a small plan anyone
# can download. The map at the end is drawn with `ras2xugrid.viz.mesh_map`, which needs the
# optional `viz` extra; the `examples` pixi environment has it (see the README).

# %%
import hashlib
import os
import shutil
import urllib.request
from pathlib import Path

import colorcet as cc
import holoviews as hv
import hvplot.pandas  # noqa: F401  # registers .hvplot and loads the Bokeh extension, once
import numpy as np
import pandas as pd

import ras2xugrid as r2x
from ras2xugrid.viz import mesh_map

# Pan is the active drag tool, so scrolling the page past a figure does not zoom it. Every plot's
# size is set where it is drawn.
hv.opts.defaults(
    hv.opts.Curve(active_tools=["pan"]),
    hv.opts.Overlay(active_tools=["pan"]),
)

# %% [markdown]
# ## Find the file
#
# The plan is `examples/data/sumwere_creek_coarse/clearWaterTestCases.p48.hdf` in
# [ClearWater-riverine](https://github.com/EcohydrologyTeam/ClearWater-riverine) (MIT licence,
# ERDC-EL), a plain 19.9 MB git blob, pinned here to commit `058d9cb`. Plan files are never
# committed to this repository (`*.hdf` is git-ignored). If the environment variable
# `HECRAS_TEST_DATA` names a folder holding the file, the notebook reads it there; otherwise it
# downloads the pinned URL once into the git-ignored `examples/data_temp/` and checks its size
# and SHA-256. What the plan file holds is described in
# [`docs/hecras-plan-files.md`](../docs/hecras-plan-files.md).

# %%
PLAN_NAME = "clearWaterTestCases.p48.hdf"
PLAN_URL = (
    "https://github.com/EcohydrologyTeam/ClearWater-riverine/raw/"
    "058d9cb4c3d2b36b5aa7c1cad0be703f7d49947b/"
    "examples/data/sumwere_creek_coarse/clearWaterTestCases.p48.hdf"
)
PLAN_BYTES = 19_871_341
# Keep in step with the cache key in .github/workflows/ci.yaml (tests/test_ci_notebook_cache.py).
PLAN_SHA256 = "9f01138412122c40b62bb28772e7da0a868f84bc6e2f86f2327bc164e9a7162b"


def is_pinned_file(path: Path) -> bool:
    """Whether ``path`` has the pinned size and SHA-256."""
    return (
        path.stat().st_size == PLAN_BYTES
        and hashlib.sha256(path.read_bytes()).hexdigest() == PLAN_SHA256
    )


def find_plan() -> Path:
    """The plan from `HECRAS_TEST_DATA` if set, else downloaded once and verified."""
    folder = os.environ.get("HECRAS_TEST_DATA")
    if folder:
        found = Path(folder) / PLAN_NAME
        if not found.is_file():
            raise FileNotFoundError(f"{PLAN_NAME} is not in HECRAS_TEST_DATA ({folder})")
        return found
    found = Path("data_temp") / PLAN_NAME
    if not found.exists():
        found.parent.mkdir(exist_ok=True)
        part = found.with_name(found.name + ".part")  # renamed only once it checks out
        with urllib.request.urlopen(PLAN_URL, timeout=60) as response, part.open("wb") as out:
            shutil.copyfileobj(response, out)
        if not is_pinned_file(part):
            part.unlink()
            raise ValueError(
                f"the download of {PLAN_NAME} is not the pinned file (size or SHA-256)"
            )
        part.rename(found)
    elif not is_pinned_file(found):
        raise ValueError(
            f"{found.name} is not the pinned file (size or SHA-256 differs); delete it"
        )
    return found


# %%
plan_path = find_plan()
plan_path.name, plan_path.stat().st_size

# %% [markdown]
# ## List the flow areas
#
# [`list_flow_areas`](../README.md#functions) reads only the file's geometry table, so it is cheap
# and tells you what is in a plan before you open any results. It replaces the first lines of the
# a hand-written reader (chore 1), which opens the HDF5 groups to look for the area's name.

# %%
areas_df = r2x.list_flow_areas(plan_path)
areas_df

# %% [markdown]
# ## Open the area as a `UgridDataset`
#
# `open_flow_area` returns the mesh and the results together. The selected variables and times
# are read into memory when the area is opened; for a large plan pass `variables=` and `time=` to
# read only what you need. It replaces hand-built cell and face tables (chore 1), a hand-typed start
# date (the time axis comes from the file's own `Time Date Stamp`, chore 5) and a hand-typed CRS
# (it comes from the file's projection, chore 5).

# %%
uds = r2x.open_flow_area(plan_path)
uds

# %% [markdown]
# Inspect before trusting. The dataset's attributes are HEC-RAS's file attributes, unchanged,
# plus `flow_area`.

# %%
uds.attrs

# %% [markdown]
# The mesh is a [`Ugrid2d`](https://deltares.github.io/xugrid/api/xugrid.Ugrid2d.html). HEC-RAS
# cells are xugrid's *faces* and HEC-RAS faces are xugrid's *edges*: the dimension names say so.
# The grid carries the file's CRS, here UTM zone 16N in metres.

# %%
uds.grid.n_face, uds.grid.n_edge, uds.grid.crs.name

# %% [markdown]
# Every variable keeps HEC-RAS's attributes, `Units` included, beside a lower-case `units` that
# xarray and xugrid read. `depth` is the one variable that is not HEC-RAS's: `ras2xugrid`
# derives it as `Water Surface - Cells Minimum Elevation`, and its `derivation` attribute says so.

# %%
for name in ["Cells Minimum Elevation", "Water Surface", "depth", "Face Flow"]:
    print(name, uds[name].attrs, sep="\n  ")

# %% [markdown]
# **A label to read with care.** Sumwere Creek's results are metric (`Units System: SI Units`,
# `Water Surface` in `m`, `Face Flow` in `m^3/s`), yet HEC-RAS labels `Cell Volume` `ft^3`:
# the volumes are very likely cubic metres under that label (see
# [`docs/hecras-plan-files.md`](../docs/hecras-plan-files.md), where the label is marked inferred).
# The net-flow checks below, which compare the change in `Cell Volume` per second with
# `Face Flow` in `m^3/s`, agree with that reading. `ras2xugrid` does not correct a HEC-RAS label,
# so the string below is what the file says.

# %%
uds["Cell Volume"].attrs["Units"], uds.attrs["Units System"]

# %% [markdown]
# The time coordinate is timestamps from `Time Date Stamp`, with HEC-RAS's `Time` (in days) kept
# beside it as `time_days`. The 5,761 steps are 30 s apart over two days.

# %%
uds["time"].values[[0, 1, -1]], uds["time_days"].attrs

# %% [markdown]
# ## Sections as the boundary of a few cells
#
# This replaces chores 2 and 4: picking cells, finding their faces by filtering
# `Faces Cell Indexes`, and the sign convention. `boundary_faces` takes named sets of cell
# indexes and returns the faces on each set's boundary, with `sign` +1 where the face's first
# cell is inside the set (positive is flow out of the set). A face shared by two cells of the set
# cancels, so nothing is double counted and no spatial join "also selects neighbouring faces".
#
# Cell indexes would normally come from a spatial join with your own points (such as pipe
# nodes). To stay reproducible here, we pick two sets from the results themselves:
#
# 1. **The cells that hold the inflow boundary faces.** `ras2xugrid` does not expose HEC-RAS's
#    boundary-condition lines, so we use the *perimeter* faces (those with a ghost cell, `-1`,
#    in `Faces Cell Indexes`) where `Face Flow` is into the mesh in more than 90% of the steps.
#    Positive `Face Flow` runs from a face's first cell to its second, so a perimeter face whose
#    first cell is the mesh cell has outflow `+Face Flow`, and `-Face Flow` otherwise.
# 2. **A wet interior set:** the cell with the largest time-mean `depth` that touches no
#    perimeter face, plus the cells it shares a face with.

# %%
edge_dim, cell_dim = uds.grid.edge_dimension, uds.grid.face_dimension
# `uds.obj` is the plain xarray Dataset; a UgridDataset refuses a subset that breaks the mesh.
face_cells = uds["Faces Cell Indexes"].values
perimeter_edges = np.flatnonzero((face_cells < 0).any(axis=1))
mesh_is_first = face_cells[perimeter_edges, 0] >= 0
perimeter_cells = np.where(
    mesh_is_first, face_cells[perimeter_edges, 0], face_cells[perimeter_edges, 1]
)
perimeter_flow = uds.obj["Face Flow"].isel({edge_dim: perimeter_edges}).values
into_mesh = -perimeter_flow * np.where(mesh_is_first, 1, -1)  # m^3/s, positive into the mesh
persistent = (into_mesh > 0).mean(axis=0) > 0.9
len(perimeter_edges), int(persistent.sum())

# %% [markdown]
# These are the perimeter faces whose flow is into the mesh in more than 90% of the steps. The
# table shows each face's mean and largest inflow over the run, the cell it enters and the
# position of the face's midpoint (`x`, `y`, in the mesh's coordinates); three of the four faces
# are at the same `x`, the mesh's west edge.

# %%
inflow_df = pd.DataFrame(
    {
        "edge": perimeter_edges[persistent],
        "cell": perimeter_cells[persistent],
        "x (m)": uds.grid.edge_coordinates[perimeter_edges[persistent], 0],
        "y (m)": uds.grid.edge_coordinates[perimeter_edges[persistent], 1],
        "mean inflow (m^3/s)": into_mesh[:, persistent].mean(axis=0),
        "largest inflow (m^3/s)": into_mesh[:, persistent].max(axis=0),
    }
).set_index("edge")
inflow_df

# %% [markdown]
# Two of the four reach round values, 10.0 and 5.0 m³/s, which looks like a prescribed
# inflow, and the others about 16.4 and 13.6 m³/s; the values come from `Face Flow`, so read
# them as the file's flows, not as a boundary condition we have identified. (The first output
# step is zero, so the means are a little below the largest values.)
#
# The wet interior set: the cells touching a perimeter face are excluded from the choice of
# centre, and a cell's neighbours are the cells it shares a face with.

# %%
mean_depth = uds["depth"].mean("time").values
mean_depth[perimeter_cells] = -np.inf  # a cell touching the perimeter cannot be the centre
wet_cell = int(np.argmax(mean_depth))
shares_face = (face_cells == wet_cell).any(axis=1) & (face_cells >= 0).all(axis=1)
neighbours = face_cells[shares_face][face_cells[shares_face] != wet_cell]
cells_dict = {
    "inflow cells": sorted(set(perimeter_cells[persistent].tolist())),
    "wet interior": [wet_cell, *sorted(set(neighbours.tolist()))],
}
cells_dict, float(mean_depth[wet_cell])

# %% [markdown]
# The wet cell (208) is next to cell 207, which is also an inflow cell, so the two sets share it:
# the wet set's boundary includes that cell's inflow face (face 5) as well.

# %%
faces_df = r2x.boundary_faces(uds, cells_dict)
faces_df

# %% [markdown]
# Each row of `faces_df` is one face on a set's boundary: `edge` is its index in HEC-RAS's face
# order, and `sign` is +1 when positive `Face Flow` leaves the set and -1 when it enters. A face
# shared by two cells of the same set cancels, so it is absent. This is the table that
# chore 2 builds by filtering `Faces Cell Indexes` by hand.
#
# If you already have a table of faces and their upstream cells (as hand-made stream sections
# are, chore 3), `faces_from_table` turns it into the same form.

# %% [markdown]
# ## Sum a face variable over each section
#
# `cross_section_series` replaces chore 4's loop: it sums `sign × Face Flow` over each section's
# faces at every time step. The file has no `Face Cumulative Volume` (the function's other
# default), so we ask for `Face Flow` alone. The result keeps HEC-RAS's name and attributes and
# adds a `derivation` attribute.

# %%
series_ds = r2x.cross_section_series(uds, faces_df, variables=["Face Flow"])
series_ds

# %%
series_ds["Face Flow"].attrs

# %% [markdown]
# The first set's boundary includes its inflow faces, yet its net outflow is small: the cells
# pass the inflow on through their other faces. The series is plotted at every 10th step
# (5 minutes, 577 points) to keep this notebook small, with
# [hvPlot](https://hvplot.holoviz.org/); the `Units` come from the variable.

# %%
flow_df = series_ds["Face Flow"].to_pandas()
flow_df.iloc[::10].hvplot.line(
    x="time",
    ylabel=f"Face Flow, summed with sign ({series_ds['Face Flow'].attrs['Units']})",
    cmap=cc.glasbey_category10[:2],
    height=320,
    width=800,
)

# %%
flow_df.describe().loc[["mean", "min", "max"]]

# %% [markdown]
# Net outflow is never positive in either set and the cells fill: the flow is the decrease in the
# water the cells hold (this file has no precipitation to add). Check it against `Cell Volume`.
# The change in volume per 30 s step, negated, should equal the net outflow averaged over the
# same step. A slope of 1 and a correlation near 1 also show that `Cell Volume`'s `ft^3` label
# holds cubic metres, the unit of `m^3/s` times seconds.

# %%
step_seconds = float((uds["time"].values[1] - uds["time"].values[0]) / np.timedelta64(1, "s"))
for name, cells in cells_dict.items():
    volume = uds.obj["Cell Volume"].isel({cell_dim: cells}).sum(cell_dim).values.astype("float64")
    minus_dv_dt = -np.diff(volume) / step_seconds
    net_outflow = flow_df[name].to_numpy()
    step_mean = (net_outflow[1:] + net_outflow[:-1]) / 2
    slope = np.polyfit(minus_dv_dt, step_mean, 1)[0]
    print(
        f"{name}: correlation {np.corrcoef(step_mean, minus_dv_dt)[0, 1]:.6f}, slope {slope:.4f}, "
        f"volume {volume[0]:,.0f} to {volume[-1]:,.0f}"
    )

# %% [markdown]
# ## A section drawn as a line
#
# This replaces chore 3, the hand-made list of faces for a stream section.
# `cross_section_faces` takes a [`shapely.LineString`](https://shapely.readthedocs.io/en/stable/reference/shapely.LineString.html)
# in the mesh's coordinates and returns the faces it crosses, in the same frame as
# `boundary_faces`. A face is selected when the part of the line inside a cell puts that cell's
# centroid and the centroid of the neighbouring cell across the face on opposite sides of the line,
# and the line's segment crosses the straight line joining the two centroids (xugrid's
# [`snap_to_grid`](https://deltares.github.io/xugrid/api/xugrid.Ugrid2d.snap_to_grid.html) rule),
# so the faces form a staircase beside the line, and perimeter faces are never selected.
#
# To stay reproducible, the line is the north-south line through the middle of the mesh's
# bounding box, `x = (xmin + xmax) / 2` from `uds.grid.bounds`, running from 100 m south of the
# mesh to 100 m north of it. It is drawn **south to north**, so its left is the west, where three
# of the four inflow faces in the table above enter (their `x` is the mesh's west edge), and
# positive flow crosses it from west to east. `sign` is +1 when a face's first cell is on the
# line's left.

# %%
from shapely.geometry import LineString  # noqa: E402

xmin, ymin, xmax, ymax = uds.grid.bounds
line_x = (xmin + xmax) / 2
midline = LineString([(line_x, ymin - 100.0), (line_x, ymax + 100.0)])
line_x, midline.length

# %%
line_df = r2x.cross_section_faces(uds, {"midline": midline})
line_df.head(), len(line_df), line_df["sign"].value_counts().to_dict()

# %% [markdown]
# The line crosses 30 faces, one chain that splits the mesh in two (the function raises if the
# faces form a gap, a branch or a loop). The map draws every face as a thin grey segment, the line
# in black and its selected faces in colour: the staircase the faces make beside it. The
# coordinates are nominal (see below), so there is no basemap.

# %%
nodes = uds.grid.node_coordinates
edge_nodes = uds.grid.edge_node_connectivity


def segments(edges):
    """Each face (xugrid edge) as a ``(x0, y0, x1, y1)`` row for ``hv.Segments``."""
    a, b = nodes[edge_nodes[edges, 0]], nodes[edge_nodes[edges, 1]]
    return np.column_stack([a[:, 0], a[:, 1], b[:, 0], b[:, 1]])


selected = line_df.index.get_level_values("edge").to_numpy()
columns = ["x0", "y0", "x1", "y1"]
mesh_edges = hv.Segments(pd.DataFrame(segments(np.arange(uds.grid.n_edge)), columns=columns)).opts(
    color="lightgrey", line_width=1
)
line_faces = hv.Segments(pd.DataFrame(segments(selected), columns=columns)).opts(
    color=cc.palette["glasbey_category10"][2], line_width=3
)
drawn_line = hv.Path([np.array(midline.coords)]).opts(color="black", line_width=1.5)
(mesh_edges * line_faces * drawn_line).opts(
    frame_width=800, data_aspect=1, xlabel="x (m)", ylabel="y (m)"
)

# %% [markdown]
# The series: `Face Flow` summed over these faces with `cross_section_series`, as before, plotted
# beside the two boundary sections at every 10th step.

# %%
line_series_ds = r2x.cross_section_series(uds, line_df, variables=["Face Flow"])
line_flow_df = line_series_ds["Face Flow"].to_pandas()
compare_df = pd.concat([flow_df, line_flow_df], axis=1)
compare_df.iloc[::10].hvplot.line(
    x="time",
    ylabel=f"Face Flow, summed with sign ({line_series_ds['Face Flow'].attrs['Units']})",
    cmap=cc.glasbey_category10[:3],
    height=320,
    width=800,
)

# %% [markdown]
# ### Does the line agree with the boundary sections?
#
# Three checks, using the cells west of the line (centroid x below the line's) as a set for
# `boundary_faces`.
#
# **(a) The same faces and signs.** The line's rule (+1 when the first cell is on the left) is
# `boundary_faces`' outflow rule for the set on the left. The west set's boundary faces that have
# no ghost (-1) side are the faces between the west set and the east, so they should be exactly the
# line's faces.

# %%
west_cells = np.flatnonzero(uds.grid.centroids[:, 0] < line_x)
west_df = r2x.boundary_faces(uds, {"west": west_cells})
west_edges = west_df.index.get_level_values("edge").to_numpy()
interior = (face_cells[west_edges] >= 0).all(axis=1)
interior_df = west_df[interior]
print(
    f"{len(west_cells)} west cells; {len(west_df)} boundary faces, "
    f"{int(interior.sum())} without a ghost side and {int((~interior).sum())} on the perimeter"
)
print(
    "same faces:",
    interior_df.index.get_level_values("edge").equals(line_df.index.get_level_values("edge")),
    "| same signs:",
    np.array_equal(interior_df["sign"].to_numpy(), line_df["sign"].to_numpy()),
)

# %% [markdown]
# **(b) The same series, less the perimeter faces.** The west set's boundary series also holds
# every face of the set with a ghost side: the mesh's west edge and the outer faces along the
# west half's north and south sides, with the inflow faces that enter there. The line does not
# cross them, so the line's series should equal the boundary series minus theirs. The largest
# absolute difference should be rounding only.

# %%
west_series_ds = r2x.cross_section_series(uds, west_df, variables=["Face Flow"])
perimeter_df = west_df[~interior]
perimeter_series_ds = r2x.cross_section_series(uds, perimeter_df, variables=["Face Flow"])
west_flow = west_series_ds["Face Flow"].to_pandas()["west"]
perimeter_flow_series = perimeter_series_ds["Face Flow"].to_pandas()["west"]
difference = line_flow_df["midline"] - (west_flow - perimeter_flow_series)
print(f"largest absolute difference: {difference.abs().max():.2e} m^3/s")

# %% [markdown]
# **(c) A water balance.** The net flow across the line, west to east, should equal the inflow
# through all of the west set's perimeter faces (its west edge and the outer faces along its north
# and south sides; flow out of the set through them is `perimeter_flow_series`, so inflow is its
# negative) minus the change in the set's `Cell Volume`
# per step, the check made above for the other two sets.

# %%
volume = uds.obj["Cell Volume"].isel({cell_dim: west_cells}).sum(cell_dim).values.astype("float64")
dv_dt = np.diff(volume) / step_seconds
net_across = line_flow_df["midline"].to_numpy()
step_mean = (net_across[1:] + net_across[:-1]) / 2
perimeter_out = perimeter_flow_series.to_numpy()
expected = -(perimeter_out[1:] + perimeter_out[:-1]) / 2 - dv_dt
slope = np.polyfit(expected, step_mean, 1)[0]
print(
    f"correlation {np.corrcoef(step_mean, expected)[0, 1]:.6f}, slope {slope:.4f}; "
    f"mean flow across the line {net_across.mean():.2f} m^3/s west to east"
)

# %% [markdown]
# ## Draw depth with a time slider
#
# `mesh_map` (`ras2xugrid.viz.mesh_map`) draws a cell-valued (UGRID face) variable cell by cell,
# with a time slider, re-rasterizing as you zoom. The plan has 5,761 steps, so we draw every 20th
# (10 minutes, 289 frames) of `depth`. The colour limits cover all drawn frames, so a colour
# means the same depth on every one.
#
# This file's coordinates put the mesh at a northing of about 2 km on UTM zone 16N, near 0 degrees
# latitude, so a web basemap would show open ocean. `tiles=None` leaves it off; a real project's
# mesh normally gets tiles, which is `mesh_map`'s default for a grid with a CRS.

# %%
depth_uda = uds["depth"].isel(time=slice(None, None, 20))
depth_uda.sizes

# %%
mesh_map(depth_uda, tiles=None, width=800, height=500)

# %% [markdown]
# ## What comes next
#
# The notebook now shows both ways to make a section: the boundary of cells you choose
# (`boundary_faces`, or `faces_from_table` for a table of faces) and a line drawn across the mesh
# (`cross_section_faces`). Both give the same frame, which `cross_section_series` sums.
