# Contributing

Thanks for helping. Issues and pull requests are welcome. Please read
[AGENTS.md](AGENTS.md) first: its guardrails (HEC-RAS names kept verbatim,
anti-goals, how dependencies are declared) apply to every contributor, not only
agents.

## Environment

[pixi](https://pixi.sh) manages the environment; do not use bare `pip` or
`conda` here.

```bash
pixi install --all
```

## Tasks

| Task | What it does |
| --- | --- |
| `pixi run test` | the test suite (no real plan files needed) |
| `pixi run test-local` | tests that read real plan files, if `HECRAS_TEST_DATA` is set |
| `pixi run lint` | `ruff check` |
| `pixi run format` | `ruff format` |
| `pixi run typecheck` | `pyrefly check src/ras2xugrid` |
| `pixi run -e ci test` | the tests in the environment CI tests in: core, viz and dev, without Jupyter |

Add or extend a test for any function you change. A runtime dependency goes in
one place: its PyPI name in `pyproject.toml`'s `[project.dependencies]`, which
pixi maps to a conda name; a package for the `viz` extra also goes in the `viz`
feature, in its conda name. Re-lock after a change and run
`tests/test_package_section.py`, which checks the locked record. Notebooks are
Jupytext pairs: edit the `.ipynb` in the notebook editor with the Jupytext Sync
extension, or edit the `.py` and run
`pixi run -e examples jupytext --sync examples/<name>.py`, never both at once.
See [README § Paired notebooks](README.md#paired-notebooks-jupytext).

## Tests with real plan files

Plan files are large and are never committed. Tests marked `local_data` read
real files from the folder named by `HECRAS_TEST_DATA` and are skipped when it
is not set. In bash or zsh:

```bash
HECRAS_TEST_DATA=/path/to/folder pixi run test-local
```

In PowerShell:

```powershell
$env:HECRAS_TEST_DATA = "C:\path\to\folder"; pixi run test-local
```

The folder may hold any `*.hdf` plan files; the generic real-file check runs
over all of them.

## Reporting a plan file that reads wrongly

Please do not attach a file that belongs to a client or project. Open an issue
with:

- the `ras2xugrid` version (`ras2xugrid.__version__`) and the HEC-RAS version
  that wrote the file (the file's root attributes name it);
- what you expected and what you got, with the full traceback or the wrong
  values;
- the file's structure, not its data, from `h5py`:

  ```python
  import h5py

  with h5py.File("model.p01.hdf") as f:
      f.visititems(lambda name, obj: print(name, getattr(obj, "shape", ""), getattr(obj, "dtype", "")))
  ```

  (Paste only the group and dataset names, shapes and dtypes around the part
  that fails.)
- a minimal reproduction. The easiest is to change
  `ras2xugrid.testing.write_synthetic_plan`'s output until it fails the same
  way; a PR that adds that as a test is the best report of all. Public plans,
  such as the Sumwere Creek test case in the example notebook, are also fine to
  cite.
