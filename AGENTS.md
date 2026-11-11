# AGENTS.md

Guidance for AI coding agents, and for human contributors, working in this repo. For *what the
package is* see [README.md](README.md) and the [design note](docs/design.md); for how to
contribute see [CONTRIBUTING.md](CONTRIBUTING.md). LimnoTech maintainers also follow the LimnoTech
family's internal workflow guide; everything an outside contributor needs is here.

## Critical guardrails

- **Agents commit on a branch. Agents never push, never merge, and never work on `main`.** Commit
  messages carry **no AI co-author trailer**. Create a branch (or a worktree) first. These
  written rules are the only enforcement: no hook stops you.
- **A new branch never tracks `main`.** Branch from local `main`, or add `--no-track` when
  branching from a remote ref, and check `git branch -vv` before handing back: no upstream, or the
  branch's own name.
- **Multi-step work pauses for review**: commit each step on its branch and stop for a
  maintainer's review before the next step starts.
- **Every review finding is fixed before the hand-back, Minor ones included.**
- **One runtime dependency list.** `[project.dependencies]`, in PyPI names, holds what
  `src/ras2xugrid` imports; pixi-build-python maps it to conda names for the package's record
  (see [Dependencies](#dependencies)). `pandas` implies `pyarrow`. Core has no plotting library.
  **Never depend on a private LimnoTech package**, in the manifest, the lock or CI.
- **Preserve HEC-RAS terminology verbatim.** Variable names, attribute names, `Units` and
  `Location` strings are carried as HEC-RAS writes them. Anything derived gets a new name and
  attributes saying how it was derived. In prose, paraphrase and link to the primary HEC-RAS
  documentation.
- **Anti-goals** ([docs/design.md](docs/design.md)). The package must not: correct, rename or
  convert a HEC-RAS variable silently; need HEC-RAS installed, or a Windows-only library such as
  `pythonnet`, to read a file; grow a post-processing API that xugrid already has (point
  sampling, zonal statistics, rasters, polygonizing) or a water balance (that belongs in analysis
  code on top of the package); depend on a private LimnoTech package.
- **Plan files are never committed** (`*.hdf` is git-ignored). Tests that read a real file read
  the folder in `HECRAS_TEST_DATA` and are marked `local_data`, skipped unless it is set.
- **Windows matters from the first commit**: the co-developer, Jason Rutyna, works on Windows.
  `path` arguments accept `str`, `os.PathLike` and open binary file-like objects.
- **Notebooks:** an agent edits the jupytext `.py`, never the `.ipynb`, then runs
  `pixi run -e examples jupytext --sync <name>.py` and verifies by executing headlessly. People
  edit the `.ipynb`, and the Jupytext Sync extension carries their saves into the `.py`. Before
  editing a `.py`, ask whether its notebook is open with unsaved changes: the next save of either
  file overwrites the other's changes ([README § Paired
  notebooks](README.md#paired-notebooks-jupytext)).

## Style

Python code at 88 columns; docstrings and comments at 72 (W505). A token longer
than that, such as a URL, gets `# noqa: W505` on its line. Markdown at 80
(`.markdownlint.json`, held by the markdownlint-cli2 pre-commit hook).

## Verification

`pixi run test`, `pixi run lint`, `pixi run format`, `pixi run typecheck`, and
`pixi run -e ci test` for the environment CI tests in (core, viz and dev, without Jupyter). Run
`pixi run -e ci test` before handing back or merging: `pixi run test` uses the full environment and
can pass a test that imports something only Jupyter provides.

[CI](.github/workflows/ci.yaml): a push to any branch runs on Ubuntu only; a PR into `main` runs
Ubuntu, macOS and Windows (this repository is public, so the minutes are free); a manual run
(`workflow_dispatch`, from the Actions tab) has an `os` dropdown, `windows`, `macos` or `both`
(default), and runs the notebook job but no Ubuntu tests and no typecheck. Only `main` writes the
pixi cache (a branch's or PR's cache serves no other ref and crowds older caches out), so after a
merge that changes `pixi.lock`, run the workflow manually on `main` with `both` once: that run
writes the Windows, macOS and `examples` caches that PRs and manual runs then restore. On a branch
that changes dependencies, the lock or file I/O, run it manually once pushed, rather than wait for
the PR to find a Windows-only failure.
`pixi run test-local` runs the real-file tests when `HECRAS_TEST_DATA` is set. After a dependency
change, run `grep '^\s*- pypi:' pixi.lock | sort -u`: nothing should appear, because this
repository installs itself as a source package from conda. Anything that does belongs in a
feature under its conda name. The `examples` environment shares
the `default` solve group on purpose, so ras2xugrid's own tests run against the versions the
example uses. `pixi.lock` is generated; never edit it by hand. The layout is the shared packaging
pattern: `pyproject.toml` is the single source of truth for the build, the environment (pixi) and
the tool configuration; there is no `pixi.toml` or `environment.yml`.

## Dependencies

`[project.dependencies]` is the one runtime list: what `src/` imports or names as a plugin, in PyPI
names, with a floor only where this package's own code needs it. `[tool.pixi.package.build.config]`
sets `ignore-pypi-mapping = false`, so pixi-build-python maps that list to conda names and writes
them into the record a consumer's solve takes. `[tool.pixi.package.run-dependencies]` holds only
what a PyPI name cannot say: here, `sqlite >=3.38`, declared for its own chain (no family package is
below it) because the GDAL/PROJ stack leaves it unbounded. The environment's own tools (`dev`,
`jupyter`, `examples`) live in pixi features, in conda names.

This repository is public, so it keeps its `viz` and `jupyter` extras in
`[project.optional-dependencies]` for people who `pip install`. A source package's record carries
no extras, so the `viz` feature lists the same packages in conda names for this environment, and
`run-constraints` carries the viz floors to consumers. The `viz` extra is checked against its
feature by a test, and so is the `jupyter` extra.

The mapping fails quietly, so `tests/test_package_section.py` reads the record pixi locked in
`pixi.lock` and checks each requirement is in it, with its specifier, and that `requires-python`
reached it. The rules it enforces: no family package, no environment marker, no direct reference
and no extra in `[project.dependencies]`; a PyPI-only package (none today) goes on its `PYPI_ONLY`
allowlist and each consumer declares it; where the mapping picks a narrower conda package, declare
what the code needs. It also checks the solve: where `pandas` is locked so is `pyarrow`, and
where `libgdal` is locked, `sqlite` is at least 3.38. After a manifest change, re-lock and run it.
The design, the rules and the probes behind them:
[water-data-engine's gate 3b spec](https://github.com/LimnoTech/water-data-engine/blob/main/docs/design/specs/2026-11-08-maintainability-gate-3b-design.md).

## Source package

ras2xugrid is a [pixi-build](https://pixi.sh/latest/build/getting_started/) source package
(`[tool.pixi.package]` in `pyproject.toml`), and this repository consumes itself the same way, from
`[tool.pixi.dependencies]`. A consumer that is a pixi workspace declares it under a conda
dependencies table, with the preview feature enabled:

```toml
[tool.pixi.workspace]
preview = ["pixi-build"]

[tool.pixi.dependencies]
ras2xugrid = { path = "../ras2xugrid" }
```

(In a `pixi.toml`, the tables are `[workspace]` and `[dependencies]`.) The consumer then inherits
the package's `run-dependencies` and `run-constraints` in its own solve, instead of repeating them.
A run-constraint applies to that package wherever it appears in the consumer's solve, one pulled in
only by another dependency included, and installs nothing by itself. A conda source dependency
carries no extras, so a consumer that draws maps names the viz packages itself.

- `feature.core` holds only the environment's python; `tests/test_package_section.py` holds the
  package section to the record it produces and the viz extra to the viz feature.
- The package's static `version` is the **last release**: bump it beside the `CHANGELOG.md` heading
  in each release-preparation change (a test checks the two agree). `__version__` still comes from
  hatch-vcs; the static version reaches only the conda record, where a consumer may floor it.
- pixi is pinned to `>=0.76,<0.77` (`requires-pixi`), and each `setup-pixi` step in CI sets
  `pixi-version: v0.76.0`, because pixi-build is a preview. Move both together.
- Upgrading an existing checkout in place can leave the default environment without the editable
  install (`ModuleNotFoundError: ras2xugrid`); run `pixi reinstall ras2xugrid`, or delete
  `.pixi/envs/default` and run `pixi install --locked`.

## Gotchas

- **Never name a coordinate or variable so it differs from another only by case.** `time` and
  `Time` are the same zarr path on a case-insensitive filesystem (macOS, Windows), so
  `to_zarr(zarr_format=3)` raised `ContainsArrayError`. HEC-RAS's `Time` (days) is therefore the
  coordinate `time_days`, with HEC-RAS's name in `attrs["hecras_name"]` and its `Time` = `days`
  attribute kept. `to_zarr` works; `tests/test_plan.py` pins the round trip.
  See [docs/hecras-plan-files.md](docs/hecras-plan-files.md).
