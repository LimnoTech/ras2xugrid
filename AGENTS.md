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
- **Every runtime dependency is declared twice, on purpose.** The PyPI name goes in
  `[project.dependencies]` (or its extra); the conda name goes in the matching
  `[tool.pixi.feature.*]`. Add one and you must add both, or `tests/test_dependency_parity.py`
  fails. `pandas` implies `pyarrow`. Core has no plotting library. **Never depend on
  water-data-engine or `stream-design`**, in the manifest, the lock or CI.
- **Preserve HEC-RAS terminology verbatim.** Variable names, attribute names, `Units` and
  `Location` strings are carried as HEC-RAS writes them. Anything derived gets a new name and
  attributes saying how it was derived. In prose, paraphrase and link to the primary HEC-RAS
  documentation.
- **Anti-goals** ([docs/design.md](docs/design.md)). The package must not: correct, rename or
  convert a HEC-RAS variable silently; need HEC-RAS installed, or a Windows-only library such as
  `pythonnet`, to read a file; grow a post-processing API that xugrid already has (point
  sampling, zonal statistics, rasters, polygonizing) or a water balance (that belongs in analysis
  code on top of the package); depend on water-data-engine or `stream-design`.
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
change, run `grep '^\s*- pypi:' pixi.lock | sort -u`: only `./` (the editable self-install) should
appear. Anything else belongs in a feature under its conda name. The `examples` environment shares
the `default` solve group on purpose, so ras2xugrid's own tests run against the versions the
example uses. `pixi.lock` is generated; never edit it by hand. The layout is the shared packaging
pattern: `pyproject.toml` is the single source of truth for the build, the environment (pixi) and
the tool configuration; there is no `pixi.toml` or `environment.yml`.

## Gotchas

- **Never name a coordinate or variable so it differs from another only by case.** `time` and
  `Time` are the same zarr path on a case-insensitive filesystem (macOS, Windows), so
  `to_zarr(zarr_format=3)` raised `ContainsArrayError`. HEC-RAS's `Time` (days) is therefore the
  coordinate `time_days`, with HEC-RAS's name in `attrs["hecras_name"]` and its `Time` = `days`
  attribute kept. `to_zarr` works; `tests/test_plan.py` pins the round trip.
  See [docs/hecras-plan-files.md](docs/hecras-plan-files.md).
