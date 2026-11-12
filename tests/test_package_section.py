"""Hold ras2xugrid's package section to its one dependency list, and the
pins around it.

ras2xugrid is a pixi-build source package (water-data-engine's
pin-propagation spec, revision 2; the maintainability round's gate 3b):
a consumer that names it under a conda ``[dependencies]`` table gets its
conda record in its own solve. With ``ignore-pypi-mapping = false``,
pixi-build-python writes that record from ``[project.dependencies]``
(PyPI names, mapped to conda names) plus
``[tool.pixi.package.run-dependencies]``. The mapping drops a
requirement it cannot map without a word: a family package, a
requirement with an environment marker, a direct reference, a PyPI-only
name, or any name the mapping service was not reachable for during the
lock (water-data-engine's ``examples/sandbox/pypi_mapping/log.md``). The
record test below reads the record pixi locked and fails on each of
those. ``[project.optional-dependencies]`` (the public ``viz`` and
``jupyter`` extras) never reach a record, so the record test ignores
them.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

import ras2xugrid

REPO = Path(__file__).resolve().parents[1]

# PyPI-only requirements (no conda-forge build): none.
PYPI_ONLY: set[str] = set()

# Where the conda name is not one of the usual spellings `conda_names`
# tries.
RENAMES: dict[str, str] = {}

# The family packages this package takes, each a source package from the
# checkout beside it: none, ras2xugrid is the bottom of its chain and
# never depends on a private LimnoTech package.
UPSTREAMS: set[str] = set()

# Family packages that reach this package only through an upstream: none
# (the user's rule 2 of 2026-11-08: don't declare a package only because
# a dependency brings it in).
TRANSITIVE: set[str] = set()

# Today's viz floors (2026-11-06), written out so a change to them is a
# visible decision.
VIZ_FLOORS = {
    "colorcet": ">=3.2.1",
    "holoviews": ">=1.23",
}


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def lock() -> dict:
    return yaml.safe_load((REPO / "pixi.lock").read_text(encoding="utf-8"))


def package(pyproject: dict) -> dict:
    return pyproject["tool"]["pixi"]["package"]


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(requirement: str) -> str:
    return re.split(r"[\s<>=!~;\[@(]", requirement.strip(), maxsplit=1)[0]


def requirement_specifier(requirement: str) -> str:
    """The version specifier of a requirement with no marker or direct
    reference, spaces removed."""
    rest = requirement.strip()[len(requirement_name(requirement)) :]
    return re.sub(r"\s+", "", rest)


def conda_names(pypi: str) -> set[str]:
    """The conda spellings a PyPI name usually maps to."""
    base = normalize(pypi)
    names = {base, base.replace("-", "_")}
    names |= {
        f"python-{base}",
        f"py-{base}",
        f"{base}-base",
        f"{base}-core",
        f"{base}-python",
    }
    if base in RENAMES:
        names.add(RENAMES[base])
    return {normalize(n) for n in names}


def self_records(pyproject: dict, lock: dict) -> dict[str, dict]:
    """The package's own record (``conda_source: <name>[...] @ .``) for
    each declared platform.

    Fails naming the platform whose default environment has none, so a
    lock made for fewer platforms than the workspace declares cannot
    pass on the records it does have.
    """
    name = package(pyproject)["name"]
    packages = {
        str(p.get("conda_source")): p for p in lock["packages"] if "conda_source" in p
    }
    environment = lock["environments"]["default"]["packages"]
    records = {}
    for platform in pyproject["tool"]["pixi"]["workspace"]["platforms"]:
        sources = [
            e["conda_source"]
            for e in environment.get(platform, [])
            if str(e.get("conda_source", "")).startswith(f"{name}[")
            and str(e["conda_source"]).endswith("@ .")
        ]
        assert len(sources) == 1, f"{platform}: {len(sources)} self records for {name}"
        records[platform] = packages[sources[0]]
    return records


def test_conda_names_tries_the_usual_spellings():
    assert {"matplotlib-base", "pyarrow-core", "python-libarchive-c"} <= (
        conda_names("matplotlib") | conda_names("pyarrow") | conda_names("libarchive-c")
    )
    assert "pandas" in conda_names("pandas")


def test_requirement_specifier_drops_the_name_and_spaces():
    assert requirement_specifier("pandas >= 3, <4") == ">=3,<4"
    assert requirement_specifier("glm-py") == ""


def test_the_mapping_is_on(pyproject):
    """Without it, [project.dependencies] never reaches the record and
    consumers get only python."""
    assert package(pyproject)["build"]["config"]["ignore-pypi-mapping"] is False


def test_no_requirement_has_a_marker_or_a_direct_reference(pyproject):
    """The mapping drops a marked requirement on every platform and
    turns a direct reference into the conda package of that name (rules
    3 and 4)."""
    bad = [r for r in pyproject["project"]["dependencies"] if ";" in r or "@" in r]
    assert bad == []


def test_no_requirement_asks_for_an_extra(pyproject):
    """A source package's record carries no extras (the probe's question
    5), so `pkg[extra]` would reach consumers as plain `pkg`."""
    assert [r for r in pyproject["project"]["dependencies"] if "[" in r] == []


def test_pypi_only_names_are_requirements(pyproject):
    """The allowlist names only real requirements, so it cannot hide a
    typo."""
    if not PYPI_ONLY:
        pytest.skip("no PyPI-only package")
    names = {
        normalize(requirement_name(r)) for r in pyproject["project"]["dependencies"]
    }
    assert PYPI_ONLY <= names


def test_every_requirement_reaches_the_record(pyproject, lock):
    """Each requirement not on PYPI_ONLY is in every self record's
    depends, by one of its conda names, with its specifier. A wrong name
    would pass a count, and the repo's own PyPI solve would install the
    right package, so its tests pass while consumers break."""
    missing = []
    for record in self_records(pyproject, lock).values():
        depends: dict[str, set[str]] = {}
        for entry in record.get("depends", []):
            name, _, spec = entry.partition(" ")
            depends.setdefault(normalize(name), set()).add(re.sub(r"\s+", "", spec))
        for requirement in pyproject["project"]["dependencies"]:
            name = requirement_name(requirement)
            if normalize(name) in PYPI_ONLY:
                continue
            wanted = requirement_specifier(requirement)
            specs = set().union(*(depends.get(n, set()) for n in conda_names(name)))
            if not specs or (wanted and wanted not in specs):
                missing.append(f"{record['conda_source']}: {requirement}")
    assert missing == [], (
        "requirements missing from the record (re-lock after a manifest change)"
    )


def test_requires_python_reaches_the_record(pyproject, lock):
    wanted = re.sub(r"\s+", "", pyproject["project"]["requires-python"])
    for record in self_records(pyproject, lock).values():
        assert f"python {wanted}" in record.get("depends", []), record["conda_source"]


def test_pypi_only_names_are_not_in_the_record(pyproject, lock):
    """If one appears, conda-forge has gained a build: take it off the
    allowlist."""
    if not PYPI_ONLY:
        pytest.skip("no PyPI-only package")
    for record in self_records(pyproject, lock).values():
        names = {normalize(entry.split()[0]) for entry in record.get("depends", [])}
        for pypi in PYPI_ONLY:
            assert not (names & conda_names(pypi)), (
                f"{pypi} is in {record['conda_source']}"
            )


def test_upstreams_are_source_packages_in_the_run_dependencies(pyproject):
    """A family package goes only in run-dependencies (rule 1): the
    self-consumed package brings it into this repo's own environment, so
    it is not named again under [tool.pixi.dependencies]; in
    [project.dependencies] or any pypi-dependencies, pixi would look for
    it on PyPI."""
    if not UPSTREAMS:
        pytest.skip("no family package")
    pixi = pyproject["tool"]["pixi"]
    run_dependencies = package(pyproject)["run-dependencies"]
    pypi_tables = [pixi.get("pypi-dependencies", {})]
    pypi_tables += [
        f.get("pypi-dependencies", {}) for f in pixi.get("feature", {}).values()
    ]
    conda_tables = [pixi.get("dependencies", {})]
    conda_tables += [
        f.get("dependencies", {}) for f in pixi.get("feature", {}).values()
    ]
    wheel = {
        normalize(requirement_name(r)) for r in pyproject["project"]["dependencies"]
    }
    for name in UPSTREAMS:
        declared = run_dependencies[name]
        assert isinstance(declared, dict) and declared.get("path") == f"../{name}", name
        assert name not in wheel, f"{name} is in [project.dependencies]"
        assert all(name not in t for t in pypi_tables), f"{name} is a PyPI dependency"
        assert all(name not in t for t in conda_tables), f"{name} is named twice"


def test_upstreams_reach_the_lock_as_source_packages(pyproject, lock):
    """Each upstream is in every self record's depends and locked from
    its sibling checkout as a source package on every platform (rule 1's
    self-consumption, the probe's 8c)."""
    if not UPSTREAMS:
        pytest.skip("no family package")
    environment = lock["environments"]["default"]["packages"]
    for platform, record in self_records(pyproject, lock).items():
        names = {normalize(entry.split()[0]) for entry in record.get("depends", [])}
        sources = [str(e.get("conda_source", "")) for e in environment[platform]]
        for name in UPSTREAMS:
            assert name in names, f"{platform}: {name} is not in the record"
            assert any(
                s.startswith(f"{name}[") and s.endswith(f"@ ../{name}") for s in sources
            ), f"{platform}: {name} is not locked as a source package"


def test_transitive_family_packages_are_not_declared(pyproject):
    """A family package that reaches this one only through an upstream
    is never declared here."""
    if not TRANSITIVE:
        pytest.skip("no family package")
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    for name in TRANSITIVE:
        assert not re.search(rf"^\s*{re.escape(name)}\s*=", text, flags=re.MULTILINE), (
            name
        )


def test_the_package_consumes_itself(pyproject):
    assert pyproject["tool"]["pixi"]["dependencies"]["ras2xugrid"] == {"path": "."}
    assert "ras2xugrid" not in pyproject["tool"]["pixi"].get("pypi-dependencies", {})


def locked_names(entry: dict) -> str | None:
    """The package name of a lock environment entry: a conda URL's file
    name, or a PyPI wheel's or sdist's; None for a source package
    (``conda_source``)."""
    url = entry.get("conda") or entry.get("pypi")
    if not url:
        return None
    filename = url.rsplit("/", 1)[-1].split("#", 1)[0]
    if "conda" in entry:
        stem = re.sub(r"\.(conda|tar\.bz2)$", "", filename)
        return normalize(stem.rsplit("-", 2)[0])
    return normalize(re.split(r"-\d", filename, maxsplit=1)[0])


def locked_version(entry: dict) -> str:
    filename = (entry.get("conda") or "").rsplit("/", 1)[-1]
    return re.sub(r"\.(conda|tar\.bz2)$", "", filename).rsplit("-", 2)[1]


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version)[:3])


def locked_platforms(lock: dict):
    """Each (environment, platform, entries) the lock holds."""
    for env_name, env in lock["environments"].items():
        for platform, entries in env["packages"].items():
            yield env_name, platform, entries


def test_locked_names_reads_conda_and_pypi_entries():
    conda = {
        "conda": "https://conda.anaconda.org/conda-forge/osx-arm64/pyarrow-core-26.0.0-py312h_1_cpu.conda"
    }
    pypi = {
        "pypi": "https://files.pythonhosted.org/packages/0f/b7/ab/pcodec-1.1.0-cp312-cp312-macosx_11_0_arm64.whl"
    }
    assert locked_names(conda) == "pyarrow-core"
    assert locked_version(conda) == "26.0.0"
    assert locked_names(pypi) == "pcodec"
    assert locked_names({"conda_source": "x[1] @ ."}) is None
    assert version_tuple("3.38.2") >= (3, 38)


def test_pyarrow_is_locked_wherever_pandas_is(lock):
    """pandas 3 backs its default str dtype with pyarrow only when
    pyarrow is installed, and conda-forge's pandas does not require it
    (the gate-3b spec). pyarrow-core provides the module.
    """
    missing = []
    for env_name, platform, entries in locked_platforms(lock):
        names = {locked_names(e) for e in entries}
        if "pandas" in names and not names & {"pyarrow", "pyarrow-core"}:
            missing.append(f"{env_name}/{platform}")
    assert missing == [], "pandas is locked without pyarrow"


def test_sqlite_is_at_least_3_38_wherever_libgdal_is(lock):
    """proj and libspatialite leave sqlite unbounded, and GDAL needs
    3.38 (python-stack-gotchas, pixi and conda-forge); the floor is
    declared once, at the bottom of the family."""
    too_old = []
    for env_name, platform, entries in locked_platforms(lock):
        by_name = {locked_names(e): e for e in entries if "conda" in e}
        if not {"libgdal", "libgdal-core"} & set(by_name):
            continue
        sqlite = by_name.get("sqlite") or by_name.get("libsqlite")
        if sqlite is None or version_tuple(locked_version(sqlite)) < (3, 38):
            too_old.append(f"{env_name}/{platform}")
    assert too_old == [], "libgdal is locked beside sqlite older than 3.38"


def test_python_has_no_ceiling(pyproject):
    assert "<" not in pyproject["project"]["requires-python"]


def spec(text: str) -> str:
    """A version specifier with its spaces removed, for comparing conda
    and PEP 508 text."""
    return re.sub(r"\s+", "", text)


def conda_floor(spec_: object) -> str:
    """The version part of a pixi conda spec, spaces removed, or "" when
    it is unconstrained."""
    if isinstance(spec_, dict):
        spec_ = spec_.get("version", "*")
    text = spec(str(spec_))
    return "" if text == "*" else text


def test_viz_extra_is_in_the_viz_feature(pyproject):
    """The public `viz` extra (for pip users) and this repository's own
    `viz` feature (conda names) list the same packages, with the same
    floors. The extra never reaches the record, so this is the only
    thing keeping the two in step."""
    extra = {
        normalize(requirement_name(r)): requirement_specifier(r)
        for r in pyproject["project"]["optional-dependencies"]["viz"]
    }
    feature = pyproject["tool"]["pixi"]["feature"]["viz"]["dependencies"]
    conda = {normalize(name): conda_floor(value) for name, value in feature.items()}
    assert set(extra) <= set(conda), (
        f"in the viz extra, not the feature: {sorted(set(extra) - set(conda))}"
    )
    disagree = {n: (extra[n], conda[n]) for n in extra if spec(extra[n]) != conda[n]}
    assert not disagree, f"floors differ (extra, conda): {disagree}"
    assert {n: v for n, v in conda.items() if v} == VIZ_FLOORS


def test_jupyter_extra_is_in_the_jupyter_feature(pyproject):
    """The public `jupyter` extra (for pip users) names only packages
    the `jupyter` feature has."""
    extra = {
        normalize(requirement_name(r))
        for r in pyproject["project"]["optional-dependencies"]["jupyter"]
    }
    feature = pyproject["tool"]["pixi"]["feature"]["jupyter"]["dependencies"]
    assert extra <= {normalize(name) for name in feature}


def test_run_constraints_are_the_viz_floors(pyproject):
    """A viz floor that is not a run-constraint never reaches a consumer
    that draws maps."""
    run_constraints = {
        name: conda_floor(value)
        for name, value in package(pyproject)["run-constraints"].items()
    }
    assert run_constraints == VIZ_FLOORS


def test_run_dependencies_hold_only_the_sqlite_floor(pyproject):
    """The runtime list is [project.dependencies]; the run-dependencies
    add only what a PyPI name cannot say. ras2xugrid declares sqlite for
    its own chain (no family package is below it)."""
    assert set(package(pyproject)["run-dependencies"]) == {"sqlite"}


def test_core_feature_holds_only_python(pyproject):
    """The runtime list is [project.dependencies]; the environment needs
    only its interpreter."""
    assert set(pyproject["tool"]["pixi"]["feature"]["core"]["dependencies"]) == {
        "python"
    }


def test_package_version_is_the_latest_release(pyproject):
    """The package version is the newest released CHANGELOG heading,
    bumped at each release.

    ``__version__`` still comes from hatch-vcs (``_version.py``), never
    from this field.
    """
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    released = re.findall(r"^## \[?(\d+(?:\.\d+)*)\]?", changelog, flags=re.MULTILINE)
    assert released, "CHANGELOG.md has no released '## x.y.z' heading"
    assert package(pyproject)["version"] == released[0]

    assert pyproject["tool"]["hatch"]["version"]["source"] == "vcs"
    assert "version" in pyproject["project"]["dynamic"]
    from ras2xugrid import _version

    assert ras2xugrid.__version__ == _version.__version__


def test_ci_environment_has_no_jupyter_stack():
    """The self-package brings in only its record, never the Jupyter
    stack.

    The ci environment does hold the viz stack (its own feature), so
    only Jupyter is checked.
    """
    pixi = shutil.which("pixi")
    if pixi is None:
        pytest.skip("pixi is not on PATH")
    listed = subprocess.run(
        [pixi, "list", "--environment", "ci", "--frozen", "--json"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    names = {entry["name"] for entry in json.loads(listed.stdout)}
    assert "ras2xugrid" in names
    present = names & {"jupyterlab", "jupytext", "hvplot"}
    assert not present, (
        f"the ci environment has Jupyter or examples packages: {sorted(present)}"
    )


def satisfies(version: str, specifier: str) -> bool:
    """Whether a dotted version meets a comma-joined ``>=``/``<``/``==``
    specifier.

    Raises ValueError naming the text for a version that is not dotted
    numbers (``latest``) or an operator this does not read (``~=``,
    ``!=``).
    """

    def parts(text: str) -> tuple[int, ...]:
        if not re.fullmatch(r"v?\d+(\.\d+)*", text):
            raise ValueError(f"not a dotted numeric version: {text!r}")
        return tuple(int(p) for p in text.lstrip("v").split("."))

    compare = {
        ">=": lambda a, b: a >= b,
        ">": lambda a, b: a > b,
        "<=": lambda a, b: a <= b,
        "<": lambda a, b: a < b,
        "==": lambda a, b: a[: len(b)] == b,
    }
    for clause in spec(specifier).split(","):
        match = re.fullmatch(r"(>=|<=|==|>|<)([^<>=!~]+)", clause)
        if match is None:
            raise ValueError(f"unsupported specifier {clause!r} in {specifier!r}")
        op, bound = match.groups()
        if not compare[op](parts(version), parts(bound)):
            return False
    return True


def test_satisfies_reads_requires_pixi_ranges():
    assert satisfies("v0.84.2", ">=0.84.2")
    assert not satisfies("0.84.1", ">=0.84.2")
    assert satisfies("v0.84.2", ">=0.84.2,<0.85")
    assert not satisfies("v0.85.0", ">=0.84.2,<0.85")


def test_satisfies_names_a_version_it_cannot_read():
    with pytest.raises(ValueError, match="'latest'"):
        satisfies("latest", ">=0.84.2")


@pytest.mark.parametrize("specifier", ["~=0.84", "!=0.85", ">=0.84.2,!=0.84.3"])
def test_satisfies_refuses_an_unsupported_specifier(specifier):
    with pytest.raises(ValueError, match="unsupported specifier"):
        satisfies("0.84.2", specifier)


def setup_pixi_steps(workflow: dict) -> list[dict]:
    """The prefix-dev/setup-pixi steps of a parsed workflow."""
    return [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps") or []
        if str(step.get("uses", "")).startswith("prefix-dev/setup-pixi")
    ]


def pixi_pin_problems(workflow: dict, required: str | None) -> list[str]:
    """What is wrong with the workflow's pixi pins, one message per
    step; empty if nothing."""
    problems = []
    for step in setup_pixi_steps(workflow):
        name = step.get("name", step["uses"])
        version = (step.get("with") or {}).get("pixi-version")
        if version is None:
            problems.append(f"{name!r} sets no pixi-version")
        elif required:
            try:
                inside = satisfies(str(version), required)
            except ValueError as error:
                problems.append(f"{name!r}: pixi-version {version!r}: {error}")
            else:
                if not inside:
                    problems.append(
                        f"{name!r}: pixi-version {version!r} is outside {required!r}"
                    )
    return problems


def workflow_with(step_with: object) -> dict:
    return {
        "jobs": {
            "j": {
                "steps": [
                    {
                        "name": "Setup pixi",
                        "uses": "prefix-dev/setup-pixi@v0",
                        "with": step_with,
                    }
                ]
            }
        }
    }


def test_an_empty_with_is_reported_not_raised():
    assert pixi_pin_problems(workflow_with(None), ">=0.84.2") == [
        "'Setup pixi' sets no pixi-version"
    ]


def test_a_non_numeric_pixi_version_is_reported_with_its_step():
    (problem,) = pixi_pin_problems(
        workflow_with({"pixi-version": "latest"}), ">=0.84.2"
    )
    assert problem.startswith("'Setup pixi': pixi-version 'latest'")


def test_an_unsupported_requires_pixi_is_reported():
    (problem,) = pixi_pin_problems(workflow_with({"pixi-version": "v0.84.2"}), "~=0.84")
    assert "unsupported specifier" in problem


def test_ci_pins_the_pixi_version(pyproject):
    """pixi-build is a preview, so CI runs the pixi the lock was last made
    or checked with."""
    workflow = yaml.safe_load(
        (REPO / ".github/workflows/ci.yaml").read_text(encoding="utf-8")
    )
    assert setup_pixi_steps(workflow), "no setup-pixi step found in ci.yaml"
    required = pyproject["tool"]["pixi"]["workspace"].get("requires-pixi")
    problems = pixi_pin_problems(workflow, required)
    assert not problems, "; ".join(problems)


def test_requires_pixi_is_a_floor_only(pyproject):
    required = pyproject["tool"]["pixi"]["workspace"]["requires-pixi"]
    assert re.fullmatch(r">=\d+\.\d+\.\d+", required), required


def test_ci_pins_the_floor_version(pyproject):
    floor = pyproject["tool"]["pixi"]["workspace"]["requires-pixi"][2:]
    workflow = yaml.safe_load(
        (REPO / ".github/workflows/ci.yaml").read_text(encoding="utf-8")
    )
    pins = {s["with"]["pixi-version"] for s in setup_pixi_steps(workflow)}
    assert pins == {f"v{floor}"}


def test_the_canary_runs_the_latest_pixi():
    canary = yaml.safe_load(
        (REPO / ".github/workflows/pixi-canary.yaml").read_text(encoding="utf-8")
    )
    # PyYAML reads the bare key `on` as True.
    triggers = canary.get("on", canary.get(True))
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    (step,) = setup_pixi_steps(canary)
    assert step["with"]["pixi-version"] == "latest"
    assert step["with"]["cache"] is False
    assert step["with"]["locked"] is True
