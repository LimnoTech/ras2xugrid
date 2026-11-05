# What ras2xugrid relies on in a HEC-RAS plan file

A short reference to the facts about HEC-RAS 2D plan files (HDF5) that the reader depends on. HEC
documents the file format only in part, so these are observations of real files, not guarantees
for every version.

Each fact carries a marker:

- **[V]** checked: against a source opened for this note, or by running a command on a file. The
  commands run on the public file are listed, with their output, in [How checked](#how-checked),
  and each fact names its check (`[V: check 3]`).
- **[I]** inferred or derived from what was checked, not observed directly.
- **[U]** not checked.

[V] means checked on the files named, not true of every plan.

## The files

| File | HEC-RAS | Units system | Real cells | Faces | Face points |
| --- | --- | --- | --- | --- | --- |
| Sumwere Creek, `clearWaterTestCases.p48.hdf` | 6.4.1 | SI | 367 | 915 | 549 |
| a HEC-RAS 6.6 plan | 6.6 | not recorded | tens of thousands | | |
| a HEC-RAS 6.7 plan with a pipe network | 6.7 | US customary | tens of thousands | | |

Sumwere Creek is the coarse test case of
[ClearWater-riverine](https://github.com/EcohydrologyTeam/ClearWater-riverine) (MIT licence),
`examples/data/sumwere_creek_coarse/clearWaterTestCases.p48.hdf` at commit `058d9cb`; the example
notebook [`examples/sumwere_creek.py`](../examples/sumwere_creek.py) downloads it into
`examples/data_temp/` and checks its SHA-256. Every Sumwere fact below was checked on 2026-11-04
with the commands in [How checked](#how-checked). The other two plans are project files that
cannot be shared; their facts were checked by a probe on 2026-11-02 and are marked
"6.6 plan" or "6.7 plan".

Plan files never enter this repository. `pixi run test-local` runs the real-file tests
(`tests/test_real_files.py`) on every plan in the folder named by `HECRAS_TEST_DATA`.

Sumwere's counts are from `list_flow_areas` [V: check 1]. The two project plans are each tens of
thousands of cells [V: by probe]; their exact figures are not published.

## Paths

- Areas are listed in the compound dataset `Geometry/2D Flow Areas/Attributes` (fields `Name`,
  `Cell Count` and others), never from the group's members: the group also holds `Attributes`,
  `Cell Info`, `Cell Points`, `Polygon Info`, `Polygon Parts` and `Polygon Points`, which are not
  areas. Sumwere's one area is `Perimeter 1`. [V: check 2]
- Geometry: `Geometry/2D Flow Areas/<area>/` holds `FacePoints Coordinate`,
  `Cells FacePoint Indexes`, `Faces FacePoint Indexes`, `Faces Cell Indexes`,
  `Cells Surface Area` and `Cells Minimum Elevation`. [V: check 2; the 6.7 plan]
- Results: `Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/` holds `Time`,
  `Time Date Stamp` and `2D Flow Areas/<area>/`. Some members of the area's group are groups, not
  results: `Boundary Conditions` and `Computations` in Sumwere, and also `Reference Lines` in the
  6.7 plan. [V: check 4; the 6.7 plan]
- Pipe nodes: `Geometry/Pipe Nodes` (`Attributes`, `Points`). The 6.7 plan has them, with HEC-RAS's
  own field names, including the misspelt `Condtui Connections (US:DS)`, which `pipe_nodes` keeps.
  [V: the 6.7 plan] Sumwere has no pipe network, and `pipe_nodes` returns an empty frame.
  [V: check 7]

## Ghost rows

A result array on cells is wider than `Cell Count`: Sumwere's are 444 wide for 367 real cells (77
ghost rows), and 77 faces have a ghost neighbour [V: check 3]; the 6.7 plan's are likewise wider
than its `Cell Count`, with as many faces having a ghost neighbour as there are ghost rows
[V: the 6.7 plan]. A ghost cell has an index of `Cell Count` or more in `Faces Cell Indexes`.
The reader drops ghost rows from cells and writes -1 for a ghost neighbour. Face arrays are as
wide as the face count (915 in Sumwere). [V: check 3]

## `Location` spellings

Each result array has a `Location` attribute saying whether it is on cells or faces.

| Array | `Location` | `Units` | File |
| --- | --- | --- | --- |
| `Cell Volume`, `Water Surface`, the two `Cell Eddy Viscosity` arrays | `Cells` | `ft^3`, `m`, `m^2/s` | Sumwere [V: check 4] |
| `Face Flow`, `Face Velocity`, `Face Eddy Viscosity` | `Faces` | `m^3/s`, `m/s`, `m^2/s` | Sumwere [V: check 4] |
| `Cell Cumulative Excess Depth`, `Cell Cumulative Infiltration Depth`, `Cell Cumulative Precipitation Depth` | `Cell` | `in` | the 6.7 plan [V] |
| `Cell Volume`, `Water Surface` | `Cells` | `ft^3`, `ft` | the 6.7 plan [V] |
| `Face Cumulative Volume`, `Face Flow`, `Face Velocity` | `Faces` | `ft^3`, `cfs`, `ft/s` | the 6.7 plan [V] |

The singular `Cell` appears on the 6.7 plan's three cumulative-depth arrays only, so the reader
accepts `Cell` and `Cells`, `Face` and `Faces`: matching only the plural would drop
precipitation. [V: the 6.7 plan] Sumwere and the 6.6 plan write `Cells` and `Faces` on every array
they hold. [V: check 4; the 6.6 plan] Every array in the area's results group of the three files
has time as its first axis, which `open_flow_area`'s length check assumes. [V: check 4; the 6.6
and 6.7 plans]

Sumwere's `Cell Volume` says `ft^3` in a file whose `Units System` is `SI Units` and whose
`Water Surface` is in `m`, so the label is very likely wrong [I]. The reader copies `Units`
verbatim and does not correct it; check a `Units` string against the file's `Units System`
before converting. [V: check 4 for the strings]

## `Time` and `Time Date Stamp`

- `Time Date Stamp` is a fixed-width byte string, `|S19`, written like `13MAY2022 00:00:00`; the
  values are 18 bytes, so the last byte is a NUL pad [V: check 5 for the width and lengths; I for
  why]. English month abbreviations; no time zone, so the reader returns naive timestamps [I]. The
  6.7 plan has the same width and form. [V: the 6.7 plan]
- Neither Sumwere (midnight is written `14MAY2022 00:00:00`) nor the 6.7 plan writes a
  `24:00:00` hour [V: check 5; the 6.7 plan]; the reader still reads one as 00:00 of the next
  day, in case another version does [U whether any does].
- `Time` is in days from the start, with the attribute `Time` = `days`: Sumwere has 5,761 steps
  from `-0.0` to `2.0` (30 s apart), and the 6.7 plan's also starts at `-0.0`. [V: check 5; the
  6.7 plan]
- The dataset holds `time` (timestamps) and `time_days` (this `Time`, with its `Time` = `days`
  attribute and `hecras_name` = `Time`). It is not called `Time` because on a case-insensitive
  filesystem (macOS, and Windows by default) `time` and `Time` are the same zarr array path, and
  `to_zarr(zarr_format=3)` raises `ContainsArrayError` (`to_netcdf` works). [V: check 8, on
  macOS]

## `Projection`

A root attribute holding ESRI WKT. Sumwere's is `NAD_1983_UTM_Zone_16N`, and
`pyproj.CRS.from_wkt(...).to_epsg()` returns 26916 at `min_confidence` 100, 70 and 25.
[V: check 6] The 6.7 plan's is a State Plane zone in US survey feet, and `to_epsg()` identifies it
at every `min_confidence` from 100 to 25. [V: the 6.7 plan] A file without the attribute needs
`crs=`. The root attributes of both files are `File Type`, `File Version`, `Projection` and
`Units System` (`SI Units` in Sumwere, `US Customary` in the 6.7 plan). [V: check 6; the 6.7 plan]

## Static and derived cell variables

- `Cells Minimum Elevation` is in the area's geometry in Sumwere and the 6.7 plan. [V: check 2;
  the 6.7 plan]
- `Cell Hydraulic Depth` is in the 6.6 plan's results but not in Sumwere's or the 6.7 plan's, so
  for those two `open_flow_area` adds `depth = Water Surface - Cells Minimum Elevation`, with a
  `derivation` attribute saying it is not a HEC-RAS output. [V: check 7; the 6.6 and 6.7 plans]

## Sign of `Face Flow`

`Face Flow` is positive from the first to the second cell of `Faces Cell Indexes`. The check takes
the interior faces (both cells real) at every time step where the water-surface difference between
the two cells exceeds 0.05 (in the file's length unit) and the flow is not zero, and compares the
sign of the flow with the sign of first-cell minus second-cell water surface:

- Sumwere, all 5,761 steps: 49,453 of 49,453 agree; on the last step 10 of 10, and on the step of
  largest total |`Face Flow`| (index 5751) 10 of 10. [V: check 9]
- The 6.7 plan, all steps (threshold 0.05 ft): every face decided agrees. [V: the 6.7 plan]

For other plans and versions the rule is [I]. The single-step samples are small, so the all-steps
figures carry the claim. `tests/test_real_files.py` repeats the check on every plan in
`HECRAS_TEST_DATA` and asserts at least 99% agreement: slack for plans not yet seen, since the
plans measured agree 100%.

## Points in cells

`boundary_faces` takes the cells inside a section as indexes; cells under points (such as pipe
nodes used as outlets) come from xugrid's `Ugrid2d.locate_points`, which returns -1 for a point
outside the mesh, and `boundary_faces` refuses -1. [V: `boundary_faces`'s docstring] In the 6.7
plan, each pipe node used as an outlet fell in one real cell, more than a foot from the nearest
face and face point, so none lay on a face. [V: the 6.7 plan] A
point exactly on a face or face point lies in two or more cells, and which one `locate_points`
returns is not defined here: check the distance before trusting it. [I]

## How checked

Run from a clone of this repository after `pixi install`, with the file downloaded by the example
notebook (or copied there by hand). Run on 2026-11-04 on macOS with h5py 3.16.0, xarray 2026.9.0,
zarr 3.4.2, xugrid 0.15.3 and pyproj from the `default` environment. Set the two shell variables
first:

```bash
P=examples/data_temp/clearWaterTestCases.p48.hdf
R="Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
```

**Check 1**, the counts:

```bash
pixi run python -c "
import ras2xugrid as r; print(r.list_flow_areas('$P').T)"
```

```text
name                                      Perimeter 1
Cell Count                                        367
faces                                             915
face_points                                       549
File Version                  HEC-RAS 6.4.1 June 2023
Plan Title    sw_Crs_PP_CC_May2022_2Day_10x_1s_30sOut
```

**Check 2**, the members of the geometry groups:

```bash
pixi run python -c "
import h5py; g = h5py.File('$P')['Geometry/2D Flow Areas']
print(list(g)); print(g['Attributes']['Name'], g['Attributes'].dtype.names[-1])
print(sorted(g['Perimeter 1']))"
```

```text
['Attributes', 'Cell Info', 'Cell Points', 'Perimeter 1', 'Polygon Info', 'Polygon Parts', 'Polygon Points']
[b'Perimeter 1'] Cell Count
['Cells Center Coordinate', "Cells Center Manning's n", 'Cells Face and Orientation Info', 'Cells Face and Orientation Values', 'Cells FacePoint Indexes', 'Cells Minimum Elevation', 'Cells Surface Area', 'Cells Volume Elevation Info', 'Cells Volume Elevation Values', 'FacePoints Cell Index Values', 'FacePoints Cell Info', 'FacePoints Coordinate', 'FacePoints Face and Orientation Info', 'FacePoints Face and Orientation Values', 'FacePoints Is Perimeter', 'Faces Area Elevation Info', 'Faces Area Elevation Values', 'Faces Cell Indexes', 'Faces FacePoint Indexes', 'Faces Low Elevation Centroid', 'Faces Minimum Elevation', 'Faces NormalUnitVector and Length', 'Faces Perimeter Info', 'Faces Perimeter Values', 'Perimeter']
```

**Check 3**, ghost rows: `Cell Count`, the widths of a cell and a face array, the faces with a
ghost neighbour, and the largest cell index in `Faces Cell Indexes`:

```bash
pixi run python -c "
import h5py; f = h5py.File('$P'); g = f['Geometry/2D Flow Areas']
n = int(g['Attributes']['Cell Count'][0]); c = g['Perimeter 1/Faces Cell Indexes'][:]
r = f['$R/2D Flow Areas/Perimeter 1']
print(n, r['Water Surface'].shape, r['Face Flow'].shape, (c >= n).any(axis=1).sum(), c.max())"
```

```text
367 (5761, 444) (5761, 915) 77 443
```

**Check 4**, each member of the area's results group: `Location`, `Units`, and whether its first
axis is as long as `Time`:

```bash
pixi run python -c "
import h5py; t = h5py.File('$P')['$R']; nt = len(t['Time'])
for k, v in t['2D Flow Areas/Perimeter 1'].items():
    print(k, v.attrs['Location'].decode(), v.attrs['Units'].decode(), v.shape[0] == nt) if hasattr(v, 'shape') else print(k, 'group')"
```

```text
Boundary Conditions group
Cell Eddy Viscosity - Eddy Viscosity X Cells m^2/s True
Cell Eddy Viscosity - Eddy Viscosity Y Cells m^2/s True
Cell Volume Cells ft^3 True
Computations group
Face Eddy Viscosity Faces m^2/s True
Face Flow Faces m^3/s True
Face Velocity Faces m/s True
Water Surface Cells m True
```

**Check 5**, `Time Date Stamp` (type, first and last, the lengths of the values without NUL
padding, how many end in `24:00:00`, and the stamps around the first midnight) and `Time`:

```bash
pixi run python -c "
import h5py; t = h5py.File('$P')['$R']; s = t['Time Date Stamp'][:]
print(s.dtype, s[0], s[-1], {len(x.rstrip(b'\0')) for x in s}, sum(x.endswith(b' 24:00:00') for x in s))
print(s[2879:2882]); print(len(t['Time']), t['Time'][0], t['Time'][-1], t['Time'].attrs['Time'])"
```

```text
|S19 b'13MAY2022 00:00:00' b'15MAY2022 00:00:00' {18} 0
[b'13MAY2022 23:59:30' b'14MAY2022 00:00:00' b'14MAY2022 00:00:30']
5761 -0.0 1.9999999999949793 b'days'
```

**Check 6**, the root attributes and the CRS:

```bash
pixi run python -c "
import h5py, pyproj; f = h5py.File('$P'); print(sorted(f.attrs), f.attrs['Units System'])
w = f.attrs['Projection'].decode(); print(w[:40], [pyproj.CRS.from_wkt(w).to_epsg(c) for c in (100, 70, 25)])"
```

```text
['File Type', 'File Version', 'Projection', 'Units System'] b'SI Units'
PROJCS["NAD_1983_UTM_Zone_16N",GEOGCS["G [26916, 26916, 26916]
```

**Check 7**, pipe nodes, `Cell Hydraulic Depth` and the derived `depth`:

```bash
pixi run python -c "
import ras2xugrid as r; print(len(r.pipe_nodes('$P')))
u = r.open_flow_area('$P'); print('Cell Hydraulic Depth' in u, dict(u['depth'].attrs))"
```

```text
0
False {'units': 'm', 'derivation': 'Water Surface - Cells Minimum Elevation (ras2xugrid; not a HEC-RAS output)'}
```

**Check 8**, `time` and `Time` as zarr paths (no plan file needed; on macOS):

```bash
pixi run python -c "
import xarray as xr, tempfile; ds = xr.Dataset(coords={'time': [0, 1], 'Time': ('time', [0.0, 1.0])})
ds.to_zarr(tempfile.mkdtemp() + '/t.zarr', zarr_format=3)" 2>&1 | tail -1
```

```text
zarr.errors.ContainsArrayError: An array exists in store LocalStore('file:///var/folders/.../t.zarr') at path 'Time'.
```

The path named was `time` in one run and `Time` in another; either way the two names collide.

**Check 9**, the sign of `Face Flow`: all steps, the last step, and the step of largest total
|`Face Flow`| (index, faces decided, faces agreeing):

```bash
pixi run python -c "
import h5py, numpy as np; f = h5py.File('$P')
c = f['Geometry/2D Flow Areas/Perimeter 1/Faces Cell Indexes'][:]; r = f['$R/2D Flow Areas/Perimeter 1']
ws = r['Water Surface'][:]; q = r['Face Flow'][:]; i = (c < 367).all(axis=1)
h = ws[:, c[i, 0]] - ws[:, c[i, 1]]; m = q[:, i]; ok = lambda h, m: ((d := (abs(h) > 0.05) & (m != 0)).sum(), (np.sign(m[d]) == np.sign(h[d])).sum())
k = np.abs(m).sum(axis=1).argmax(); print(ok(h, m), ok(h[-1], m[-1]), k, ok(h[k], m[k]))"
```

```text
(np.int64(49453), np.int64(49453)) (np.int64(10), np.int64(10)) 5751 (np.int64(10), np.int64(10))
```
