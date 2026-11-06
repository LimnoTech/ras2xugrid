# Changelog

## Unreleased

- ras2xugrid is a pixi-build source package (`[tool.pixi.package]`), and this repository installs
  itself from it. A consumer that is a pixi workspace can declare
  `ras2xugrid = { path = "../ras2xugrid" }` under `[tool.pixi.dependencies]` (a `[dependencies]`
  table in a `pixi.toml`), with `preview = ["pixi-build"]` in `[tool.pixi.workspace]`, and inherit
  its run-dependencies and the viz floors. The package's static version is the last release,
  bumped at each release; `__version__` still comes from hatch-vcs. pixi is pinned to 0.76
  (`requires-pixi`, and `pixi-version` in CI). Upgrading an existing checkout in place can leave
  the default environment without the editable install (`ModuleNotFoundError: ras2xugrid`); run
  `pixi reinstall ras2xugrid`, or delete `.pixi/envs/default` and run `pixi install --locked`.

## 0.1.0 (2026-11-05)

The first release.

- Read a HEC-RAS 2D plan file with `h5py` (no HEC-RAS, Windows or `pythonnet` needed):
  `list_flow_areas`, `open_flow_area` (an `xugrid.UgridDataset` with HEC-RAS's names, attributes
  and units kept verbatim, and a `time` coordinate beside HEC-RAS's `Time` in days as
  `time_days`) and `pipe_nodes`.
- Find the faces a line crosses, signed by the line's direction: `cross_section_faces`.
- Find the faces on the boundary of a set of cells, or take them from a table:
  `boundary_faces` and `faces_from_table`.
- Sum signed face results over cross sections: `cross_section_series`.
- Draw a cell-valued (UGRID face) variable cell by cell with a time slider: `ras2xugrid.viz.mesh_map`
  (the optional `viz` extra).
- Write a small synthetic plan file for tests: `ras2xugrid.testing.write_synthetic_plan`.
- An example notebook on ClearWater-riverine's Sumwere Creek plan
  (`examples/sumwere_creek.py`), and tests against real plan files (`pixi run test-local`, with
  `HECRAS_TEST_DATA` set).
