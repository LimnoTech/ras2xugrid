# ras2xugrid

`ras2xugrid` is for modellers who want to analyse and visualize HEC-RAS 2D
results with the scientific Python stack: [xarray](https://docs.xarray.dev/)'s
labelled arrays and time selection, pandas and GeoPandas for tables and
geometry, and [HoloViz](https://holoviz.org/) (HoloViews, Datashader, hvPlot)
for interactive maps that draw every cell of a large mesh.

HEC-RAS writes a run's results to an HDF5 plan file as bare arrays, one per
variable, kept apart from the mesh they belong to. Most work after a run needs
the two together: a map of depths cell by cell, flow summed across a road or a
stream section, values at gauges, or results handed on to a water-quality model.
`ras2xugrid` reads the plan file into
[xugrid](https://deltares.github.io/xugrid/), which follows the
[UGRID conventions](https://ugrid-conventions.github.io/ugrid-conventions/), the
community standard for unstructured-grid data in netCDF. The mesh and its
results arrive as one dataset; xugrid's own selection, regridding, plotting and
netCDF export work on it directly; and a result saved with xugrid opens in other
UGRID-aware tools, such as QGIS's mesh layers, not only in HEC-RAS.

The mesh becomes a `xugrid.Ugrid2d` and the results a `xugrid.UgridDataset`, and
face flows can be summed across named cross sections. HEC-RAS variable names,
attributes and `Units` strings are kept exactly as HEC-RAS writes them; anything
derived gets a new name and attributes saying how. It reads the file with
`h5py`, so it runs on Windows, macOS and Linux, with no HEC-RAS installation.

## How it fits with other tools

- [RAS Commander](https://github.com/gpt-cmdr/ras-commander) automates HEC-RAS
  projects (editing and running plans) and reads results from plan files into
  pandas and GeoPandas tables.
- [rashdf](https://github.com/fema-ffrd/rashdf) reads geometry and results from
  HEC-RAS HDF files into GeoPandas and xarray.
- `ras2xugrid` keeps the mesh topology and the results together as one UGRID
  dataset, for work that needs the mesh: per-cell maps, cross-section fluxes,
  regridding, export to UGRID netCDF. It can be used alongside either of the
  others.

Design note: [docs/design.md](docs/design.md); what the package reads from a
plan file: [docs/hecras-plan-files.md](docs/hecras-plan-files.md). Status:
version `0.1.0`, alpha. The API may still change.

## Example

```python
import ras2xugrid as r2x
from ras2xugrid.viz import mesh_map           # needs the `viz` extra

plan = "model.p01.hdf"                        # a HEC-RAS 2D plan file
areas_df = r2x.list_flow_areas(plan)          # one row per 2D flow area
uds = r2x.open_flow_area(plan)                # mesh + results, as a xugrid.UgridDataset
uds["Face Flow"]                              # HEC-RAS's own names, attributes and units
mesh_map(uds["Water Surface"])                # cell by cell, with a time slider (`viz` extra)

faces_df = r2x.cross_section_faces(uds, lines_gdf)   # faces each line crosses, signed
flow_ds = r2x.cross_section_series(uds, faces_df, variables=["Face Flow"])
```

`lines_gdf` is a `geopandas.GeoDataFrame` of `LineString`s in the plan's CRS.
The [example notebook](#example-notebook) runs all of this on a public plan.

## Functions

| Function | Returns |
| --- | --- |
| `list_flow_areas(path)` | one row per 2D flow area |
| `open_flow_area(path, area=None, *, variables=None, time=None, crs=None)` | the mesh and its results, as a `xugrid.UgridDataset` |
| `pipe_nodes(path)` | the plan's pipe nodes (name, x, y, attributes) |
| `boundary_faces(uds, cells)` | the faces on the boundary of a set of cells, with a flow sign |
| `cross_section_faces(uds, lines, *, max_distance=None)` | the faces each line crosses, signed by the line's direction (left to right is positive) |
| `faces_from_table(uds, df)` | the same, from a table of `CrossSection`, `Face`, `US_Cell` |
| `cross_section_series(uds, faces, variables=...)` | summed signed face values per cross section |
| `ras2xugrid.viz.mesh_map(uda, *, cmap=None, clim=None, tiles="CartoLight", alpha=0.8, **opts)` | a cell-valued (UGRID face) variable drawn cell by cell with a time slider, as a `holoviews.DynamicMap`; needs the `viz` extra and is imported from `ras2xugrid.viz` |
| `ras2xugrid.testing.write_synthetic_plan(path)` | a small synthetic plan file, for tests |

Results are on `time` (timestamps) with `time_days` (HEC-RAS's `Time`, in days)
beside it.

## Install

Not yet on PyPI or conda-forge (both are planned). Install from GitHub, with the
`viz` extra if you want `ras2xugrid.viz.mesh_map`:

```bash
pip install "ras2xugrid[viz] @ git+https://github.com/LimnoTech/ras2xugrid@v0.1.0"
```

In a pixi project, as a PyPI dependency:

```bash
pixi add --pypi "ras2xugrid[viz] @ git+https://github.com/LimnoTech/ras2xugrid@v0.1.0"
```

Without `[viz]`, the package has no plotting library. To work on the package
itself, clone it and:

```bash
pixi install --all
pixi run test
```

Tasks: `test`, `test-local`, `lint`, `format`, `typecheck` (see
`[tool.pixi.tasks]` in `pyproject.toml`).

## Example notebook

[`examples/sumwere_creek.py`](examples/sumwere_creek.py) (paired with an
executed `.ipynb`) opens the Sumwere Creek test case from
[ClearWater-riverine](https://github.com/EcohydrologyTeam/ClearWater-riverine),
a small public HEC-RAS 2D plan (367 cells;
[its folder](https://github.com/EcohydrologyTeam/ClearWater-riverine/tree/058d9cb4c3d2b36b5aa7c1cad0be703f7d49947b/examples/data/sumwere_creek_coarse)
at the pinned commit). It builds sections as the boundary of a few cells, draws
one as a line across the mesh (`cross_section_faces`) and checks it against
them, sums `Face Flow` over the sections and draws depth over time with
`ras2xugrid.viz.mesh_map`. It also notes, step by step, what each call replaces
if you read HEC-RAS files with hand-written `h5py` scripts today.

It runs in the `examples` pixi environment, which adds hvPlot and the notebook
widgets to `core`, `viz` and `jupyter`. Install it once:

```bash
pixi install -e examples
```

**In VS Code (recommended).** Large interactive maps render faster in VS Code's
notebook editor than in a browser tab. With the
[Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python)
and
[Jupyter](https://marketplace.visualstudio.com/items?itemName=ms-toolsai.jupyter)
extensions installed:

1. Open the repository folder in VS Code.
2. Open `examples/sumwere_creek.ipynb`.
3. Choose **Select Kernel** → **Python Environments…** and pick the `examples`
   environment's interpreter: `.pixi/envs/examples/bin/python` (macOS, Linux) or
   `.pixi\envs\examples\python.exe` (Windows). If it is not listed, choose
   **Enter interpreter path…** and give that path.
4. **Run All**.

**In JupyterLab.** Start it from the same environment, then open the notebook in
the browser tab:

```bash
pixi run -e examples jupyter lab
```

The notebook reads `clearWaterTestCases.p48.hdf` from the folder in
`HECRAS_TEST_DATA` when that is set, and otherwise downloads the pinned 19.9 MB
file once into the git-ignored `examples/data_temp/`.

### Paired notebooks (Jupytext)

Each notebook is two files kept in step by
[Jupytext](https://jupytext.readthedocs.io/): the `.ipynb` you run, with its
outputs, and a `.py` in the "percent" format holding the same cells as plain
text (pairing is set in `pyproject.toml`'s `[tool.jupytext]`). The `.py` is the
source of truth. Pairing gives you:

- **readable reviews**: a change to the code or prose shows in the `.py` as an
  ordinary diff, without the JSON and base64 outputs of the `.ipynb`;
- **ordinary tools**: the `.py` can be searched, linted and edited like any
  Python file;
- **executed outputs kept**: the `.ipynb` still shows the maps and tables on
  GitHub, for readers who will not run it.

In VS Code, install the
[Jupytext Sync](https://jupytext.readthedocs.io/en/latest/vs-code.html)
extension (it needs jupytext 1.17.3 or later; the pixi environments have it). It
updates the paired file each time you save either one. Point it at the pixi
environment's Python, or it may pick another interpreter's jupytext: set
`jupytextSync.pythonExecutable` in your VS Code settings to
`.pixi/envs/examples/bin/python` (macOS, Linux) or
`.pixi\envs\examples\python.exe` (Windows), then reload the window.

**Who edits which file.** People work in the `.ipynb`, in the notebook editor,
where they can run cells and see outputs; Jupytext Sync carries each save into
the `.py`. Coding agents edit the `.py`, which is plain text they can change
reliably, and then sync it into the `.ipynb`. **Never edit both at once.** If
the `.ipynb` is open with unsaved changes while the `.py` changes on disk (an
agent's edit, a `git pull`, a branch switch), the next save of either file
overwrites the other's changes. Save and close the notebook before an agent or
git touches the `.py`, and reopen it afterwards.

Without the extension (or after editing the `.py`), sync and re-execute from the
command line:

```bash
pixi run -e examples jupytext --sync examples/sumwere_creek.py
pixi run -e examples jupyter nbconvert --to notebook --execute --inplace examples/sumwere_creek.ipynb
```

CI executes it on a PR into `main` and on a manual run (the `notebook` job in
`.github/workflows/ci.yaml`).

## Tests with real plan files

Plan files are large, belong to projects and are never committed. Tests that
read a real file are marked `local_data` and skipped unless the environment
variable `HECRAS_TEST_DATA` names the folder holding the files. Nothing loads a
`.env` file, so set the variable in the shell for the command. In bash or zsh:

```bash
HECRAS_TEST_DATA=/path/to/folder pixi run test-local
```

In PowerShell:

```powershell
$env:HECRAS_TEST_DATA = "C:\path\to\folder"; pixi run test-local
```

[`.env.example`](.env.example) lists the variables the code reads; it is not
loaded automatically.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), including how to report a plan file that
reads wrongly without sharing it. Coding agents: [AGENTS.md](AGENTS.md).

## Credits

`ras2xugrid` is written by Anthony Aufdenkampe and Jason Rutyna at
[LimnoTech](https://www.limno.com/), with Sarah Jordan. It builds on Sarah
Jordan's
[ClearWater-riverine](https://github.com/EcohydrologyTeam/ClearWater-riverine)
work, which first worked out the HEC-RAS HDF layout and the face and cell
handling that `ras2xugrid` reads; its Sumwere Creek plan is also the example
data. HEC-RAS is a product of the US Army Corps of Engineers'
[Hydrologic Engineering Center](https://www.hec.usace.army.mil/software/hec-ras/).

## Licence

[MIT](LICENSE), Copyright (c) 2025-2026 LimnoTech.
