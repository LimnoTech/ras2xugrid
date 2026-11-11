# Design

`ras2xugrid` reads one 2D flow area of a HEC-RAS plan file (the `.p##.hdf`
HEC-RAS writes after an unsteady run) into
[xugrid](https://deltares.github.io/xugrid/), the
[UGRID](https://ugrid-conventions.github.io/ugrid-conventions/) mesh library for
xarray. It then sums face results across cross sections, and its optional `viz`
extra draws cell values as a map. This note says what it does, what it
deliberately leaves out, and the choices a hydraulic modeller should know before
trusting its numbers. The file facts it relies on are in
[hecras-plan-files.md](hecras-plan-files.md).

## What it does, and does not do

It does:

- read the mesh and results of a 2D flow area with `h5py`, so it runs on any
  operating system without HEC-RAS installed;
- keep HEC-RAS's names, attributes and `Units` strings exactly as the file has
  them;
- find the faces of a cross section and sum signed face results across it;
- draw a cell-valued variable cell by cell (`ras2xugrid.viz.mesh_map`, with the
  `viz` extra).

It does not:

- **rename, correct or convert anything silently.** A HEC-RAS variable keeps its
  name (`Water Surface`, `Face Flow`) and its `Units`, even where HEC-RAS's
  label is wrong (one test plan labels `Cell Volume` `ft^3` in an SI file).
  Anything the package computes gets a new name and a `derivation` attribute
  saying how.
- **run or edit HEC-RAS models.** That is
  [RAS Commander](https://github.com/gpt-cmdr/ras-commander)'s work, which also
  reads plan-file results into tables;
  [rashdf](https://github.com/fema-ffrd/rashdf) reads them into GeoPandas and
  xarray. `ras2xugrid` adds the mesh topology, so results and mesh arrive as one
  UGRID dataset.
- **duplicate xugrid.** Sampling at points, rasterizing, regridding and export
  are xugrid's (`UgridDataArray.ugrid.sel_points`, `ugrid.rasterize_like`,
  `ugrid.to_netcdf` and the rest); `ras2xugrid` adds only what is specific to
  HEC-RAS.
- **compute a water balance.** Subtracting precipitation, converting units,
  aggregating volumes per period or building a downstream model's inflow table
  belongs in the analysis that uses the sums, not in the reader.
- **read 1D rivers, pipe results or the raw solver arrays.** It reads pipe-node
  locations only (`pipe_nodes`), so cells under outlet nodes can be found.

## The dataset `open_flow_area` returns

An `xugrid.UgridDataset` on one `Ugrid2d` mesh named `mesh2d`, with xugrid's
default dimension names:

| UGRID | HEC-RAS | From |
| --- | --- | --- |
| nodes | face points | `FacePoints Coordinate` |
| faces (`mesh2d_nFaces`) | cells, **real cells only** | the first `Cell Count` rows of `Cells FacePoint Indexes` |
| edges (`mesh2d_nEdges`) | faces, **in HEC-RAS's order** | `Faces FacePoint Indexes` |

So edge *i* of the mesh is HEC-RAS face *i*, and face *j* of the mesh is HEC-RAS
cell *j*: indexes from HEC-RAS's own arrays, or from another script that reads
them, carry over unchanged.

- **Ghost cells are dropped.** HEC-RAS writes extra cells outside the perimeter
  for its boundary conditions; result arrays on cells are wider than
  `Cell Count`. The reader keeps the real cells only, and `Faces Cell Indexes`,
  kept as a data variable, has -1 where a face's neighbour is a ghost cell.
- **Results** are every array in the area's results group whose `Location` is on
  cells (`Cells` or `Cell`) or on faces (`Faces` or `Face`), under its HEC-RAS
  name, with every HEC-RAS attribute copied and the CF `units` set to HEC-RAS's
  `Units`. An array with any other `Location`, or none, is skipped with a
  warning naming it.
- **Static variables**: `Cells Surface Area` and `Cells Minimum Elevation`,
  always kept.
- **Depth.** If the plan has `Cell Hydraulic Depth`, it is kept. If not, the
  dataset gains `depth = Water Surface - Cells Minimum Elevation`, labelled as
  derived.
- **Time.** `time` holds timestamps parsed from `Time Date Stamp`, naive
  (HEC-RAS stores no time zone; a `24:00:00` hour becomes 00:00 of the next
  day). HEC-RAS's own `Time`, in days, is kept beside it as `time_days`, because
  `time` and `Time` would be the same path in a zarr store on a case-insensitive
  filesystem.
- **CRS** from the file's `Projection` attribute (WKT) through pyproj; `crs=`
  overrides it or supplies one when the file has none.
- **Reading is eager.** The selected variables and times are read into memory;
  choose them with `variables=` and `time=` for a large plan.

`list_flow_areas` lists the areas of a plan (with their cell, face and
face-point counts) before you open one.

## Cross sections and their signs

A cross section is a set of HEC-RAS faces, each with a sign (+1 or -1).
`cross_section_series` sums sign × value over each section's faces, per time
step, for `Face Flow`, `Face Cumulative Volume` or any other face variable.

HEC-RAS face results are positive from the first to the second cell of
`Faces Cell Indexes`. On the plans checked, every interior face with a clear
head difference agreed
([hecras-plan-files.md § Sign of `Face Flow`](hecras-plan-files.md#sign-of-face-flow));
for other plans this is an inference, and the real-file tests check it on any
plan you give them.

Three ways to build a section, all returning the same frame (indexed by section
and edge, with a `sign` column):

- **`boundary_faces(uds, cells)`**, the boundary of a set of cells: every face
  with exactly one cell in the set, `sign` +1 when its first cell is in the set,
  so **positive is flow out of the set**. A face shared by two cells of the set
  is not on the boundary. A face to a ghost cell counts as a boundary face. Use
  it for outlets or control volumes; cells under points come from xugrid's
  `Ugrid2d.locate_points`.
- **`cross_section_faces(uds, lines)`**, a line drawn across the mesh: the faces
  whose two cells' centroids lie on opposite sides of the line, as xugrid's
  `snap_to_grid` selects them, so the faces form a staircase beside the line.
  `sign` is +1 when the face's first cell is on the line's left, so **positive
  flow crosses the line from left to right**, standing at its start and facing
  its end; reversing the line flips every sign. The faces must form one
  connected chain; a gap, a branch or a loop raises, naming the section. A
  perimeter face (one with a ghost neighbour) is never selected, so a line that
  ends at the mesh edge leaves out the face it meets there.
- **`faces_from_table(uds, df)`**, a hand-made table of `CrossSection`, `Face`
  and `US_Cell` columns: `sign` +1 when `US_Cell` is the face's first cell. This
  lets an existing face list be checked against the other two.

## Why maps draw per cell

A HEC-RAS cell has one value. A common way to draw an unstructured mesh is to
average cell values onto the nodes and interpolate across triangles, which
blends each cell with its neighbours and smooths away a wet cell beside a dry
one. `mesh_map` instead triangulates the mesh once (each triangle remembers its
cell), gives each triangle its cell's value, and rasterizes the triangles with
datashader, so a pixel inside a cell shows that cell's value exactly. The map
re-rasterizes as you zoom; where cells are smaller than a pixel, the pixel shows
their mean. A time slider covers every step, the colour range is fixed across
steps by default, and with a CRS the map is drawn over web tiles. The same
drawing works for any cell-valued UGRID mesh, such as a MODFLOW 6 DISV grid.

`import ras2xugrid` loads no plotting library; the `viz` extra adds them, and
`mesh_map` is imported from `ras2xugrid.viz`.
